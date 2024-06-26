from supervision.draw.color import ColorPalette
from supervision.video.dataclasses import VideoInfo
from supervision.video.source import get_video_frames_generator
from supervision.video.sink import VideoSink
from supervision.tools.detections import Detections, BoxAnnotator
from .utils import draw_straight_line, draw_quadrilateral, check_ball_touch_feet
from tqdm.notebook import tqdm
import numpy as np
import cv2
from ultralytics import YOLO
import time

MODEL_POSE = "yolov8x-pose.pt"
model_pose = YOLO(MODEL_POSE)

MODEL = "yolov8x.pt"
model = YOLO(MODEL)

# dict mapping class_id to class_name
CLASS_NAMES_DICT = model.model.names
# get class id ball and bottle
BALL_CLASS_ID = 32
BOTTLE_CLASS_ID = 39
PLAYER_CLASS_ID = 0  # You need to define this based on your classes

def process_video(source_video_path, target_video_path):
    source_video_path = source_video_path.strip()
    target_video_path = target_video_path.strip()

    # create VideoInfo instance
    video_info = VideoInfo.from_video_path(source_video_path)
    # create frame generator
    generator = get_video_frames_generator(source_video_path)
    # create instance of BoxAnnotator
    box_annotator = BoxAnnotator(color=ColorPalette(), thickness=1, text_thickness=1, text_scale=0.5)

    # Counter for ball hits
    ball_hit_counter = 0
    ball_miss_counter = 0

    # flag to track if the ball has entered the region
    ball_entered_region = False
    # flag to check if player has touched the ball
    ball_touched = False
    # define points and regions
    bottle_1 = [700, 500, 50, 200]
    bottle_2 = [500, 200, 50, 200]
    bottles_region = [] * 8
    wall_region = [] * 8

    # Open the target video file and process each frame
    with VideoSink(target_video_path, video_info) as sink:
        for frame in tqdm(generator, total=video_info.total_frames):
            # Perform pose estimation
            results_poses = model_pose.track(frame, persist=True)
            annotated_frame = results_poses[0].plot()
            keypoints = results_poses[0].keypoints.xy.int().cpu().tolist()
            bboxes = results_poses[0].boxes.xyxy.cpu().numpy()

            # Perform object detection
            results_obj = model.track(frame, persist=True, conf=0.1)
            tracker_ids = results_obj[0].boxes.id.int().cpu().numpy() if results_obj[0].boxes.id is not None else None
            detections = Detections(
                xyxy=results_obj[0].boxes.xyxy.cpu().numpy(),
                confidence=results_obj[0].boxes.conf.cpu().numpy(),
                class_id=results_obj[0].boxes.cls.cpu().numpy().astype(int),
                tracker_id=tracker_ids
            )

            # Filter detections to identify bottles, ball, and player
            mask_bottles = np.array([class_id == BOTTLE_CLASS_ID for class_id in detections.class_id], dtype=bool)
            bottle_detections = Detections(
                xyxy=detections.xyxy[mask_bottles],
                confidence=detections.confidence[mask_bottles],
                class_id=detections.class_id[mask_bottles],
                tracker_id=detections.tracker_id[mask_bottles]
            )

            mask_ball = np.array([class_id == BALL_CLASS_ID for class_id in detections.class_id], dtype=bool)
            ball_detections = Detections(
                xyxy=detections.xyxy[mask_ball],
                confidence=detections.confidence[mask_ball],
                class_id=detections.class_id[mask_ball],
                tracker_id=detections.tracker_id[mask_ball]
            )

            mask_player = np.array([class_id == PLAYER_CLASS_ID for class_id in detections.class_id], dtype=bool)
            player_detections = Detections(
                xyxy=detections.xyxy[mask_player],
                confidence=detections.confidence[mask_player],
                class_id=detections.class_id[mask_player],
                tracker_id=detections.tracker_id[mask_player]
            )

            # Check if two bottles, one ball, and one player are detected
            if len(bottle_detections.xyxy) > 1:
                # Get coordinates of the two bottles
                bottle_1 = bottle_detections.xyxy[0]
                bottle_2 = bottle_detections.xyxy[1]

            bottles_region = [
                (bottle_1[0], bottle_1[1]),
                (bottle_2[0], bottle_2[1]),
                (bottle_2[2], bottle_2[3]),
                (bottle_1[2], bottle_1[3])
            ]

            # Draw lines and regions
            p1, p2 = draw_straight_line(annotated_frame, bottles_region[1], bottles_region[0])
            p3, p4 = draw_straight_line(annotated_frame, bottles_region[2], bottles_region[3])

            wall_region = [p1, p2, p4, p3]
            draw_quadrilateral(annotated_frame, bottles_region)
            draw_quadrilateral(annotated_frame, wall_region)

            # Check if the ball hits the line
            if len(ball_detections.xyxy) > 0:
                for ball in ball_detections.xyxy:
                    if check_ball_touch_feet(keypoints[0], ball):
                        ball_touched = True

                    ball_center = (int((ball[0] + ball[2]) / 2), int((ball[1] + ball[3]) / 2))

                    if cv2.pointPolygonTest(np.asarray(bottles_region), ball_center, False) >= 0:
                        if ball_touched:
                            ball_hit_counter += 1
                            ball_touched = False
                            break

                    elif cv2.pointPolygonTest(np.asarray(wall_region), ball_center, False) >= 0:
                        if ball_touched:
                            print("one missed ball !!")
                            ball_miss_counter += 1
                            break

            print(f"Total Ball Hits: {ball_hit_counter}")
            print(f"Total Ball miss: {ball_miss_counter}")

            # Annotate the frame
            labels = [
                f"id:{track_id} {CLASS_NAMES_DICT[class_id]} {confidence:0.2f}"
                for _, confidence, class_id, track_id in detections
            ]
            annotated_frame = box_annotator.annotate(frame=annotated_frame, detections=detections, labels=labels)

            # Draw the counter on the frame
            cv2.putText(annotated_frame, f"Ball Hits: {ball_hit_counter}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 4, cv2.LINE_AA)
            cv2.putText(annotated_frame, f"Ball miss: {ball_miss_counter}", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 4, cv2.LINE_AA)

            # Write the annotated frame to the output video
            sink.write_frame(annotated_frame)

            # Break the loop if 'q' is pressed
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
        cv2.destroyAllWindows()

    return ball_hit_counter, ball_miss_counter
