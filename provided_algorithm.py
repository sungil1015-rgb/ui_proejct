import cv2
import numpy as np
import os

def orb_Homography(input, master_all):
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    
    ADH_Input = clahe.apply(cv2.cvtColor(input, cv2.COLOR_BGR2GRAY))
    ADH_master = clahe.apply(cv2.cvtColor(master_all, cv2.COLOR_BGR2GRAY))
    orb = cv2.ORB_create(nfeatures = 2000)
    kp1, des1 = orb.detectAndCompute(ADH_Input, None)
    orb = cv2.ORB_create(nfeatures = 1000)
    kp2, des2 = orb.detectAndCompute(ADH_master, None)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(des1, des2)
    matches = sorted(matches, key=lambda x: x.distance)

    transformed_img = input
    
    if len(matches) > 4:
        src_pts = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1,1,2)
        tem_pts = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1,1,2)
        matrix, mask = cv2.findHomography(src_pts, tem_pts, cv2.RANSAC, 1.0)
        transformed_img = cv2.warpPerspective(input, matrix, (master_all.shape[1], master_all.shape[0]))
    
    return transformed_img

def auto_top_left_points(template_all, templates):
    return [cv2.minMaxLoc(cv2.matchTemplate(template_all, t, cv2.TM_CCOEFF_NORMED))[3] for t in templates]

def template_matching(
    input_img,
    template_all,
    templates,
    save_path,
    top_left_points=None,
    output_filename="visualized_input_with_boxes.jpeg",
):
    """Perform template matching and visualize results using OpenCV instead of matplotlib."""
    input_img = orb_Homography(input_img, template_all)
    input_img_copy = input_img.copy()
    cropped_rois = []
    matching_scores = []

    if top_left_points is None:
        top_left_points = auto_top_left_points(template_all, templates)
    
    for i, (template, point) in enumerate(zip(templates, top_left_points)):
        cropped_roi = input_img[point[1]-20:point[1]+template.shape[0]+20, point[0]-20:point[0]+template.shape[1]+20]
        
        result = cv2.matchTemplate(cropped_roi, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        top_left = (point[0] + max_loc[0], point[1] + max_loc[1])
        bottom_right = (top_left[0] + template.shape[1], top_left[1] + template.shape[0])
        
        # OpenCV로 ROI에 사각형 그리기
        cv2.rectangle(input_img_copy, top_left, bottom_right, (0, 0, 255), 2)

        cropped_rois.append(cropped_roi)
        matching_scores.append(max_val)

    # Save the visualized image using OpenCV
    visualized_path = os.path.join(save_path, output_filename)
    cv2.imwrite(visualized_path, input_img_copy)

    return cropped_rois, matching_scores, input_img_copy



