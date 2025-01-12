import cv2
import mediapipe as mp
import pandas as pd
import os
import time
from tqdm import tqdm  # For progress bars
import numpy as np
from collections import deque

# Dance names
VALID_DANCE_NAMES = ['default_dance', 'griddy', 'floss', 'squabble', 'boogie_down', 'laugh', 'boogie_up']

# Initialize MediaPipe Pose
mp_drawing = mp.solutions.drawing_utils
mp_pose = mp.solutions.pose

# Function to create a dictionary with landmark data
def create_landmark_dict(landmarks, sample_number, frame_number, dance_name):
    landmark_dict = {
        'sample_number': sample_number,
        'frame_number': frame_number,
        'dance_name': dance_name
    }

    # Loop through landmarks in dictionary
    for idx, landmark in enumerate(landmarks.landmark):
        landmark_dict[f'landmark_{idx}_x'] = landmark.x
        landmark_dict[f'landmark_{idx}_y'] = landmark.y
        landmark_dict[f'landmark_{idx}_z'] = landmark.z
        landmark_dict[f'landmark_{idx}_visibility'] = landmark.visibility

    return landmark_dict

def smooth_landmarks(buffer, smoothing_window=5):
    """
    Apply a moving average filter to smooth the landmarks.

    Args:
        buffer (deque): A deque containing the recent landmark frames.
        smoothing_window (int): The number of frames to include in the moving average.

    Returns:
        np.array: Smoothed landmarks.
    """
    if len(buffer) < 1:
        return None

    # Convert buffer to numpy array
    buffer_array = np.array(buffer)  # Shape: (N, 132)

    # Apply moving average
    smoothed = np.mean(buffer_array[-smoothing_window:], axis=0)
    return smoothed

def interpolate_missing_frames(prev_frame, next_frame, num_missing):
    """
    Interpolate missing frames between prev_frame and next_frame.

    Args:
        prev_frame (dict): Previous frame data.
        next_frame (dict): Next frame data.
        num_missing (int): Number of frames to interpolate.

    Returns:
        List[dict]: List of interpolated frame dictionaries.
    """
    interpolated_frames = []

    # Loop through any missing frames
    for i in range(1, num_missing + 1):
        ratio = i / (num_missing + 1)
        interpolated_dict = {
            'sample_number': prev_frame['sample_number'],
            'frame_number': prev_frame['frame_number'] + i,
            'dance_name': prev_frame['dance_name']
        }

        # Fill in indexes in the .csv file
        for idx in range(33):
            for coord in ['x', 'y', 'z', 'visibility']:
                key = f'landmark_{idx}_{coord}'
                interpolated_dict[key] = (1 - ratio) * prev_frame[key] + ratio * next_frame[key]

        interpolated_frames.append(interpolated_dict)

    return interpolated_frames

def extract_dance_name(filename, valid_dances):
    """
    Extracts the dance name from the filename based on predefined valid dances.

    Args:
        filename (str): The name of the video file.
        valid_dances (list): List of valid dance names.

    Returns:
        str: The extracted dance name if found; otherwise, 'unknown'.
    """
    filename_lower = filename.lower()
    for dance in valid_dances:

        if dance.lower() in filename_lower:
            return dance.lower()
        
    return 'unknown'

def process_video(video_path, sample_number, frames_per_sample=96, smoothing_window=5):
    """
    Processes a single video file to extract pose landmarks.

    Args:
        video_path (str): Path to the video file.
        sample_number (int): Identifier for the sample.
        frames_per_sample (int): Number of frames to extract per sample.
        smoothing_window (int): Number of frames for smoothing.

    Returns:
        List[dict]: A list of dictionaries containing pose landmarks for each frame.
    """
    data = []

    # Capture video input
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Skip video if there are no frames to track
    if total_frames == 0:
        print(f"[WARNING] Video '{video_path}' has 0 frames. Skipping.")
        cap.release()
        return data

    # Evenly sample frames
    frame_interval = max(1, total_frames // frames_per_sample)

    # Extract the filename from the path
    video_filename = os.path.basename(video_path)

    # Extract dance name from filename and valid dance names
    dance_name = extract_dance_name(video_filename, VALID_DANCE_NAMES)

    # Skip dances that aren't in dictionary
    if dance_name == 'unknown':
        print(f"[WARNING] Dance name not found in '{video_filename}'. Skipping this video.")
        cap.release()
        return data

    # Track pose in video frame
    with mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5) as pose:
        frame_count = 0
        sampled_frames = 0
        frame_buffer = deque(maxlen=smoothing_window)  # Buffer for smoothing

        # Sample video of dance to grab landmarks
        with tqdm(total=frames_per_sample, desc=f"Processing Sample {sample_number}") as pbar:
            while cap.isOpened() and sampled_frames < frames_per_sample:
                ret, frame = cap.read()

                # Cap can't be read
                if not ret:
                    break

                if frame_count % frame_interval == 0:
                    
                    # Process the frame
                    image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = pose.process(image)

                    # Landmark poses are found
                    if results.pose_landmarks:
                        landmark_dict = create_landmark_dict(
                            results.pose_landmarks, sample_number, sampled_frames + 1, dance_name)
                        
                        # Append raw landmarks to buffer for smoothing
                        flattened_landmarks = []
                        for idx in range(33):
                            flattened_landmarks.extend([
                                landmark_dict[f'landmark_{idx}_x'],
                                landmark_dict[f'landmark_{idx}_y'],
                                landmark_dict[f'landmark_{idx}_z'],
                                landmark_dict[f'landmark_{idx}_visibility']
                            ])
                        frame_buffer.append(flattened_landmarks)

                        # Apply smoothing to landmarks
                        smoothed_landmarks = smooth_landmarks(frame_buffer, smoothing_window=smoothing_window)
                        if smoothed_landmarks is not None:
                            smoothed_dict = {
                                'sample_number': sample_number,
                                'frame_number': sampled_frames + 1,
                                'dance_name': dance_name
                            }

                            # Write to dictionary
                            for idx in range(33):
                                smoothed_dict[f'landmark_{idx}_x'] = smoothed_landmarks[idx * 4]
                                smoothed_dict[f'landmark_{idx}_y'] = smoothed_landmarks[idx * 4 + 1]
                                smoothed_dict[f'landmark_{idx}_z'] = smoothed_landmarks[idx * 4 + 2]
                                smoothed_dict[f'landmark_{idx}_visibility'] = smoothed_landmarks[idx * 4 + 3]
                            data.append(smoothed_dict)

                        sampled_frames += 1
                        pbar.update(1)
                    
                    # Handle missing landmarks by interpolating
                    else:

                        if len(data) >= 2:
                            prev_frame = data[-2]
                            next_frame = data[-1] if len(data) >= 1 else data[-1]

                            # Interpolate any missing frames
                            interpolated_frames = interpolate_missing_frames(prev_frame, next_frame, num_missing=1)
                            data.extend(interpolated_frames)
                            sampled_frames += 1
                            pbar.update(1)
                        
                        # Skip if the first frame is missing
                        else:
                            pass

                frame_count += 1

    cap.release()
    return data

def main():
    # Directories
    video_directory = 'sample_data'
    output_directory = 'dance_dataset'

    # Parameters
    frames_per_sample = 96
    
    # Number of frames to average for smoothing
    smoothing_window = 5

    # Ensure output directory exists
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)

    # Verify video directory existence
    if not os.path.exists(video_directory):
        print(f"Error: Video directory '{video_directory}' not found.")
        exit()

    # List all video files directly inside the video_directory
    video_files = [
        f for f in os.listdir(video_directory)
        if f.endswith(('.mp4', '.avi', '.mov')) and os.path.isfile(os.path.join(video_directory, f))
    ]

    print(f"Found {len(video_files)} video(s) in '{video_directory}'.")

    # Initialize data storage
    all_data = []
    sample_number = 1

    # Process each video file
    for video_file in video_files:
        video_path = os.path.join(video_directory, video_file)
        print(f"\nProcessing Video: {video_file} as Sample {sample_number}")

        # Process the video and extract data
        sample_data = process_video(
            video_path=video_path,
            sample_number=sample_number,
            frames_per_sample=frames_per_sample,
            smoothing_window=smoothing_window
        )

        # Ensure that sample data is valid
        if sample_data:
            all_data.extend(sample_data)
            print(f"Sample {sample_number} processed with {len(sample_data)} frames.")
        else:
            print(f"No pose data detected in Sample {sample_number}. Skipping.")

        sample_number += 1

    # Save data to CSV if any data was collected
    if all_data:
        df = pd.DataFrame(all_data)
        csv_filename = os.path.join(output_directory, "all_samples.csv")
        df.to_csv(csv_filename, index=False)
        print(f"\nSaved data to '{csv_filename}'.")
    
    # No data collected
    else:
        print("\nNo data collected from videos. Skipping CSV creation.")

    print("\nAll videos processed successfully.")

if __name__ == "__main__":
    main()
