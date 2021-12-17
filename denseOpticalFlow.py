import numpy as np
import cv2
import time



def draw_flow(img, flow, step=16):

    h, w = img.shape[:2]
    y, x = np.mgrid[step/2:h:step, step/2:w:step].reshape(2,-1).astype(int)
    fx, fy = flow[y,x].T

    lines = np.vstack([x, y, x-fx, y-fy]).T.reshape(-1, 2, 2)
    lines = np.int32(lines + 0.5)

    img_bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    cv2.polylines(img_bgr, lines, 0, (0, 255, 0))

    for (x1, y1), (_x2, _y2) in lines:
        cv2.circle(img_bgr, (x1, y1), 1, (0, 255, 0), -1)

    return img_bgr


def draw_hsv(flow):

    h, w = flow.shape[:2]
    fx, fy = flow[:,:,0], flow[:,:,1]

    ang = np.arctan2(fy, fx) + np.pi
    v = np.sqrt(fx*fx+fy*fy)

    hsv = np.zeros((h, w, 3), np.uint8)
    hsv[..., 0] = ang * (180 / np.pi / 2)
    hsv[..., 1] = 255
    hsv[..., 2] = np.minimum(v * 4, 255)
    bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    return bgr

def draw_contour(img,flow):

    h, w = flow.shape[:2]
    fx, fy = flow[:,:,0], flow[:,:,1]

    v = np.sqrt(fx*fx+fy*fy)

    contour = np.zeros((h, w, 1), np.uint8)

    contour[v > 3] = 255
    
    blurred = cv2.GaussianBlur(contour, (5, 5), cv2.BORDER_DEFAULT)
    
    # threshold = 80
    # canny_output = cv2.Canny(blurred, threshold, threshold * 2)

    # get the largest contour
    contours = cv2.findContours(blurred, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = contours[0] if len(contours) == 2 else contours[1]
    big_contour = max(contours, key=cv2.contourArea)

    # draw white contour on black background as mask
    mask = np.zeros((h,w), dtype=np.uint8)
    cv2.drawContours(mask, [big_contour], 0, (255,255,255), cv2.FILLED)
    
    hull = cv2.convexHull(big_contour)
    cv2.drawContours(mask, [hull], -1, (0, 255, 255), 2)
    
    cv2.imshow("hull", mask)

    # invert mask so shapes are white on black background
    mask_inv = 255 - mask

    # create new (blue) background
    bckgnd = np.full_like(img, 255)

    # apply mask to image
    image_masked = cv2.bitwise_and(img, img, mask=mask)

    # apply inverse mask to background
    bckgnd_masked = cv2.bitwise_and(bckgnd, bckgnd, mask=mask_inv)

    # add together
    result = cv2.add(image_masked, bckgnd_masked)

    # save results
    cv2.imwrite('shapes_inverted_mask.jpg', mask_inv)
    cv2.imwrite('shapes_masked.jpg', image_masked)
    cv2.imwrite('shapes_bckgrnd_masked.jpg', bckgnd_masked )
    cv2.imwrite('shapes_result.jpg', result)

    # cv2.imshow('mask', mask)
    # cv2.imshow('image_masked', image_masked)
    # cv2.imshow('bckgrnd_masked', bckgnd_masked)
    # cv2.imshow('result', result)

    return result




cap = cv2.VideoCapture(0)

suc, prev = cap.read()
prevgray = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)


while True:

    suc, img = cap.read()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # start time to calculate FPS
    start = time.time()

    flow = cv2.calcOpticalFlowFarneback(prevgray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    
    prevgray = gray

    # End time
    end = time.time()
    # calculate the FPS for current frame detection
    fps = 1 / (end - start)

    print(f"{fps:.2f} FPS")

    cv2.imshow('flow', draw_flow(gray, flow))
    # cv2.imshow('flow HSV', draw_hsv(flow))
    cv2.imshow('contour', draw_contour(gray,flow))

    key = cv2.waitKey(5)
    if key == ord('q'):
        break


cap.release()
cv2.destroyAllWindows()