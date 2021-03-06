import numpy as np

from aux_functions import *
from user_interface import PaintApp
import itertools
import threading


# ---------------   TABLE map -----------------
class TableMap:
    """ object that holds the table corners, creates a table distances map and project the
    relevant application screen into the table plane """
    def __init__(self, corners_l, corners_r, shape, map_dense=2):
        self.corners_l = corners_l
        self.corners_r = corners_r
        self.bad_corners_distances_lst = np.zeros(20)
        self.bad_corners_idx = 0
        self.bad_corners_thresh = 0.6

        self.img_shape = shape

        t_map = create_table_map(corners_l, corners_r, shape, map_dense=map_dense)
        self.map = t_map
        self.whole_map = np.zeros(t_map.shape, dtype='uint8')
        self.map_shape = self.map.shape
        self.map_points = np.array([[0, 0], [t_map.shape[1], 0], [t_map.shape[1], t_map.shape[0]], [0, t_map.shape[0]]])

    def project_map2real(self, im_l, im_r, mask_l, mask_r, application, real_touch_idxs=np.zeros((0, 2)),
                         touch_indicator=False, show_touch=False):
        """ projects the application screen into both left and right images tables """
        im_r_lst = [im_r]
        project_map_2_im_r = threading.Thread(target=self.project2right_img_thread, args=(im_r_lst, mask_r))
        project_map_2_im_r.start()  # thread for transforming the right image the right image

        # estimating the transform from the real table to the table map
        tform_mat_l, _ = cv2.findHomography(self.corners_l, self.map_points)

        # handling the touching indexes
        if real_touch_idxs.shape[0] != 0:
            map_touch_idxs = projective_points_tform(tform_mat_l, real_touch_idxs)
            map_touch_idxs = drop_outbound_points(self.map_shape, map_touch_idxs)  # dropping out of bound indexes
        else:
            map_touch_idxs = real_touch_idxs

        application.update_touches(map_touch_idxs)

        if show_touch:
            touch_map = self.map.copy()
            for idx in map_touch_idxs:
                center_coordinates, radius, color, thickness = (idx[0], idx[1]), 5, (255,255,255), -1
                cv2.circle(touch_map, center_coordinates, radius, color, thickness)
            cv2.imshow("touch map", touch_map)


        tformed_map_left = cv2.warpPerspective(self.whole_map, np.linalg.inv(tform_mat_l), (im_l.shape[1], im_l.shape[0]))
        indexes = (tformed_map_left != [0, 0, 0]) * (mask_l[:, :, None] == 0)
        indexes = indexes[:, :, 0] + indexes[:, :, 1] + indexes[:, :, 2]
        im_l[indexes, :] = tformed_map_left[indexes, :]

        project_map_2_im_r.join()
        im_r = im_r_lst[0]

        if touch_indicator and (application.running_app is not None):  # indicate the touches on the out img (black circle)
            idx = application.running_app.touchscreen.click_location
            if idx.shape[0] != 0:
                real_idx = projective_points_tform(tform_mat_l, idx[np.newaxis, :], inverse=True)
                center_coordinates, radius, color, thickness = (real_idx[0, 0], real_idx[0, 1]), 5, (0, 0, 0), -1
                cv2.circle(im_l, center_coordinates, radius, color, thickness)
        return im_l, im_r

    def project2right_img_thread(self, im_r_lst, mask_r, use_tablet=False):
        """ thrad that projects the map to the right image """
        # im_r_lst is a list that has one index, in it the im_r. it is a list so it will be mutable
        im_r = im_r_lst[0]
        tform_mat_r, _ = cv2.findHomography(self.corners_r, self.map_points)
        tformed_map_right = cv2.warpPerspective(self.whole_map, np.linalg.inv(tform_mat_r), (im_r.shape[1], im_r.shape[0]))
        indexes = (tformed_map_right != [0, 0, 0]) * (mask_r[:, :, None] == 0)
        indexes = indexes[:, :, 0] + indexes[:, :, 1] + indexes[:, :, 2]
        im_r[indexes, :] = tformed_map_right[indexes, :]
        im_r_lst[0] = im_r

    def update_whole_map(self, application):
        """ updates the map via the relevant application - opening a thread"""
        whole_map_thread = threading.Thread(target=self.screenshot_thread, args=(application,))
        whole_map_thread.start()

    def screenshot_thread(self, application):
        """ updates the map via the relevant application"""
        self.whole_map[:self.map_shape[0], :self.map_shape[1]] = application.get_whole_map()

    def table_dist_map(self, corners_l, corners_r, former_dist_map=None, show=False, check_err=True,  get_plane=False):
        """ creates a distance map for the table using the 4 corners in each image (left and right)
            calculates the plane equation with pseudo inverse and cuts it in the 4 corners shape  """
        t_seg_l = np.zeros(self.img_shape[:2])
        t_seg_l = cv2.fillPoly(t_seg_l, [corners_l], 255)  # creates a seg map from the corners
        if show:
            t_seg_r = np.zeros(self.img_shape[:2])
            t_seg_r = cv2.fillPoly(t_seg_r, [corners_r], 255)
            cv2.imshow("both segmentations", np.concatenate((t_seg_l, t_seg_r), axis=1))
        corners_distances = np.matrix(calc_distance(corners_l[:, 0], corners_r[:, 0], t_seg_l.shape[0])).T



        if check_err:
            # measures if the distances are reasonable distances to 4 corners of a rectangle table
            mini = corners_distances.min()  # closest corner (in cm)
            maxi = corners_distances.max()  # farets corner (in cm)
            diff = maxi - mini  # differance between them (in cm)
            # print(f"diff: {maxi - mini:.2f},  min: {mini:.2f}, max: {maxi:.2f}")
            self.bad_corners_idx = (self.bad_corners_idx + 1) % len(self.bad_corners_distances_lst)
            if (diff > 200) or (maxi > 600) or (mini < 20):
                self.bad_corners_distances_lst[self.bad_corners_idx] = 1
                if np.mean(self.bad_corners_distances_lst) > self.bad_corners_thresh:
                    return former_dist_map, False
                return former_dist_map, True
            # the distances make sense
            self.bad_corners_distances_lst[self.bad_corners_idx] = 0
            # print(f"invalid mean: {np.mean(self.bad_corners_distances_lst)}")


        A = np.matrix(np.c_[corners_l, np.ones(4)])
        plan = (A.T * A).I * A.T * corners_distances  # get the plan equation (solve pseudo inverse
        xx, yy = np.meshgrid(np.arange(t_seg_l.shape[1]), np.arange(t_seg_l.shape[0]))
        dist_map_t = plan[0, 0] * xx + plan[1, 0] * yy + plan[2, 0]  # create a plane
        if get_plane:
            return dist_map_t
        dist_map_t = dist_map_t * (t_seg_l != 0)  # cut the plane in the segmentation size


        self.corners_r = corners_r
        self.corners_l = corners_l
        if check_err:
            return dist_map_t, True
        else:
            return dist_map_t


def get_table_corners(image, name="", scale=1, show=False, last_seg=np.array([[None]]), jaccard_tolerance=0.7):
    """
    :param image: left image
    :param scale: resize image param
    :param show: TRUE to show image
    :param last_seg: last  table seg image
    :return: seg image, corners coordinates
    """
    if scale != 1:
        scaled = cv2.resize(image, (image.shape[1] * scale, image.shape[0] * scale), interpolation=cv2.INTER_AREA)
    else:
        scaled = image


    R, G, B = cv2.split(scaled)
    #---for G channel----
    blur_G = cv2.medianBlur(G, 7)
    sharpen_kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
    sharpen_G = cv2.filter2D(blur_G, -1, sharpen_kernel)
    #---for B channel----
    blur_B = cv2.medianBlur(B, 7)
    sharpen_B = cv2.filter2D(blur_B, -1, sharpen_kernel)
    #---for R channel----
    blur_R = cv2.medianBlur(R, 7)
    sharpen_R = cv2.filter2D(blur_R, -1, sharpen_kernel)

    #-------thresh--------
    th1, threshG = cv2.threshold(sharpen_G, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    th2, threshB = cv2.threshold(sharpen_B, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    th3, threshR = cv2.threshold(sharpen_R, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    threshG = (threshG/255)
    threshB = (threshB/255)
    threshR = (threshR/255)
    thresh = cv2.bitwise_and(threshG, threshB)
    thresh = cv2.bitwise_and(thresh, threshR)

    #----------morphology---------
    line_min_width = 15
    kernal_h = np.ones((1, line_min_width), np.uint8)
    kernal_v = np.ones((line_min_width, 1), np.uint8)
    img_bin_h = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernal_h)
    img_bin_v = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernal_v)
    img_bin_final = cv2.bitwise_and(img_bin_h, img_bin_v)

    #-------close morph--------
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (10, 10))
    close = cv2.morphologyEx(img_bin_final, cv2.MORPH_CLOSE, kernel, iterations=2)

    #----emphasis  edges------
    edges = cv2.Canny(scaled, 40, 50, apertureSize=3)
    kernel = np.ones((5, 5), np.uint8)
    dilated_value = cv2.dilate(edges, kernel, iterations=1)
    dilated_value = 1-(dilated_value/255)
    edges_thr = cv2.bitwise_and(dilated_value, close)

    seg_mask = getLargestCC(edges_thr)  # find largest compponent
    seg_mask = ConvexHullFill(seg_mask).astype('uint8')  # fill it
    # -------finding the corners-----
    # detect corners with the goodFeaturesToTrack function.
    corners = get_seg_corners(seg_mask, scale=scale, name=name, show=show)
    if scale != 1:
        seg_mask = cv2.resize(seg_mask, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_AREA)
    return corners, seg_mask


def get_seg_corners(seg_img, name="", scale=1, show=False):
    """

    :param seg_img: table binary image
    :param scale: resize image param
    :param show: TRUE to show image
    :return: corners coordinates
    """
    # make it 3 channels and resize for better resolution
    seg_img = np.concatenate([seg_img[:, :, np.newaxis], seg_img[:, :, np.newaxis], seg_img[:, :, np.newaxis]], 2).astype('uint8')

    seg_img_gray = cv2.cvtColor(seg_img, cv2.COLOR_BGR2GRAY)
    contours, _ = cv2.findContours(seg_img_gray, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    contour = contours[0]
    perimeter = cv2.arcLength(contour, True)
    corners = cv2.approxPolyDP(contour, 0.01 * perimeter, True)[:4, 0, :]
    corners = list(corners)

    center = (sum([p[0] for p in corners]) / len(corners), sum([p[1] for p in corners]) / len(corners))
    corners.sort(key=lambda p: math.atan2(p[1] - center[1], p[0] - center[0]))  # sort by polar angle
    corners = np.array(corners)
    corners = (corners/scale).round().astype('int')
    if show:
        resized_seg_img = cv2.resize(seg_img, (int(seg_img.shape[1] / scale), int(seg_img.shape[0] / scale)),
                                     interpolation=cv2.INTER_AREA)
        for point in corners:
            x, y = point
            cv2.circle(resized_seg_img, (x, y), resized_seg_img.shape[0]//80, 255, -1)
        cv2.drawContours(resized_seg_img, [corners], -1, (0, 0, 255))
        cv2.imshow(name, resized_seg_img)
    return corners


def create_table_map(corners_l, corners_r, im_shape, map_dense=2):
    table_shape_x = np.max([300, 200])
    table_shape_y = np.min([300, 200])
    return np.zeros([table_shape_y, table_shape_x, 3], dtype="uint8")


def get_table_sizes(corners, distances, shape, x_opening=87, y_opening=56):
    """ x_opening = 87  in degrees, y_opening = 56  in degrees
    calculates the length of the table sides """
    width = shape[1]
    height = shape[0]
    x_mid = width//2
    y_mid = height//2
    deg_x = x_opening/width
    deg_y = y_opening/height

    p = np.zeros((4, 3))
    for i in range(4):
        r = distances[i]
        phi = (corners[i, 0] - x_mid) * deg_x
        theta = (corners[i, 1] - y_mid) * deg_y
        # phi = corners[i, 0] * deg_x
        # theta = corners[i, 1] * deg_y
        phi = np.deg2rad(phi)
        theta = np.deg2rad(theta)
        p[i] = np.array([r, phi, theta])

    lengths = [0, 0, 0, 0]
    for i in range(4):
        r1, phi1, theta1 = p[i]
        r2, phi2, theta2 = p[(i + 1) % 4]
        angles = np.sin(theta1) * np.sin(theta2) * np.cos(phi1 - phi2) + np.cos(theta1) * np.cos(theta2)
        lengths[i] = np.sqrt(r1**2 + r2**2 - 2 * r1 * r2 * angles)
    return lengths


class CornersFollower:
    """ object that designed to follow 4 table corners """
    def __init__(self, first_frame, err_tolerance=10, static_cam=False, show=False, name="follower"):
        self.static_cam = static_cam
        self.name = name
        self.err_tolerance = err_tolerance
        self.skip_that_frame = -1
        self.current_corners, seg_img = get_table_corners(first_frame, scale=5, name="left", show=show)
        self.zero_img = np.zeros_like(seg_img)
        self.lines = [np.zeros((0, 2), dtype=np.int)] * 4

        self.corners2lines()  # creates the initial lines with the initial corners
        self.colors = [(0, 255, 0), (255, 0, 255), (255, 0, 0), (0, 0, 255)]
        if show:
            cpy = first_frame.copy()
            for line, color in zip(self.lines, self.colors):
                for point in line:
                    x, y = point
                    cv2.circle(cpy, (int(x.round()), int(y.round())), 2, color, -1)
            cv2.imshow(self.name+": initial point lines", cpy)

        self.old_gray = cv2.cvtColor(first_frame, cv2.COLOR_BGR2GRAY)
        self.next_frame = first_frame
        self.lk_params = dict(winSize=(30, 30),
                              maxLevel=6,
                              criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03))

        self.renew_hough_time = 1  # renews the lines with the segmentation every renew_seg_time
        self.renew_hough_cnt = 0

    def corners2lines(self, mask=None):
        """runs on a, b, c, d  and  d, a, b, c   corners
        append the points that are in the line that is between each couple of corners """
        for i, (p1, p2) in enumerate(zip(self.current_corners, np.roll(self.current_corners, shift=1, axis=0))):
            img = cv2.line(self.zero_img.copy(), tuple(p1), tuple(p2), 255)
            if mask is not None:
                img = img * (mask == 0)
            points = np.where(img)
            self.lines[i] = np.array([points[1], points[0]], dtype=np.float32).T

    def renew_lines(self, mask):
        """renews the lines and updates the current corners"""

        new_table_corners = get_corners_with_lin_reg(points=self.lines)

        size = 40
        edges = cv2.Canny(self.next_frame, 400, 500, apertureSize=3)
        side_edges = []
        for i, (p1, p2) in enumerate(zip(new_table_corners, np.roll(new_table_corners, shift=1, axis=0))):

            edges_line = cv2.line(self.zero_img.copy(), tuple(p1), tuple(p2), 255, size) * edges
            if mask is not None:
                edges_line = edges_line * (mask == 0)
            side_edges.append(edges_line.copy())

        # new_table_corners = self.get_corners_with_lin_reg(points=tmp_lines)
        self.renew_hough_cnt += 1
        if self.renew_hough_cnt == self.renew_hough_time:
            try:
                new_table_corners = get_corners_with_hough(side_edges)
                self.renew_hough_cnt = 0
            except:  # if hough went wrong
                self.renew_hough_cnt -= 2

        # changing the corners if the change is reasonable
        changed = False
        if self.reasonable_change(new_table_corners):
            self.current_corners = new_table_corners  # update the current corners
            changed = True
        return changed

    def reasonable_change(self, new_table_corners):
        """ return true if the changes in the corners were reasonable"""
        pairs_diff_thresh = 50  # bigger = loser  (used 3)

        distances = np.sort(((self.current_corners - new_table_corners) ** 2).sum(1) ** 0.5)

        diff3_2 = distances[3] - distances[2] <= pairs_diff_thresh
        diff2_1 = distances[2] - distances[1] <= pairs_diff_thresh
        diff1_0 = distances[1] - distances[0] <= pairs_diff_thresh

        # there must be at least 2 corner changes
        minimum_corners_changed = (distances > 0).sum() >= 2

        # reasonable = minimum_corners_changed and differences_between_changes
        reasonable = diff3_2 and diff2_1 and diff1_0 and minimum_corners_changed

        return reasonable

    def follow(self, next_frame, mask, show=False, show_out=False):
        """ following the 4 corners of the table to the next frame"""
        if self.static_cam:
            changed = False
            return self.current_corners, changed
        self.next_frame = next_frame
        gray_frame = cv2.cvtColor(next_frame, cv2.COLOR_BGR2GRAY).copy()
        self.corners2lines(mask)
        if show:
            cpy = next_frame.copy()
            for line, color in zip(self.lines, self.colors):
                for point in line:
                    x, y = point
                    cv2.circle(cpy, (int(x.round()), int(y.round())), 2, color, -1)
            cv2.imshow(self.name+": following point lines - before renewing the lines", cpy)

        for i, line in enumerate(self.lines):
            lk_out = cv2.calcOpticalFlowPyrLK(self.old_gray, gray_frame, line, None, **self.lk_params)
            new_points, status, error = lk_out
            try:  # if there are no good indexes at all
                good_idx = (status[:, 0] != 0) & (error[:, 0] < self.err_tolerance)
            except:
                continue
            new_points = new_points[good_idx]
            # if there are not enough points at add - don't change the former line
            if len(new_points) > 4:
                self.lines[i] = new_points
        self.old_gray = gray_frame
        changed = self.renew_lines(mask)  # renews the lines and updates the current corners

        if show_out:
            cpy = next_frame.copy()
            for line, color in zip(self.lines, self.colors):
                for point in line:
                    x, y = point
                    cv2.circle(cpy, (int(x.round()), int(y.round())), 2, color, -1)
            cv2.imshow(self.name+": renewed lines and corners", cpy)

        return self.current_corners, changed

    def show_lines(self, img):
        img = img.copy()
        for i, (p1, p2) in enumerate(zip(self.current_corners, np.roll(self.current_corners, shift=1, axis=0))):
            img = cv2.line(img, tuple(p1), tuple(p2), self.colors[i], 5)
        cv2.imshow(self.name + " lines", img)


if __name__ == "__main__":

    import os
    from hands_handling import hands_matches_points

    # dirs = ["moving_table_with_hidden_corners", "smallgapimverygay", "movingtablewithhands",
    #         "biggapimgay", "moving_table2", "movingtableilovedicks", "movingtablewithhandimeatingintheass",
    #         "first_one"]  # 0 to 7
    dirs = ["2_removing_table", "2_removing_table_hands", "2_hand_no_sleeve", "2_static_table"]
    two_masked = True
    use_right = True
    videos_dir = os.path.join(os.getcwd(), "videos", dirs[1])
    left_vid_path = os.path.join(videos_dir, 'regular_video_left.mp4')
    right_vid_path = os.path.join(videos_dir, 'regular_video_right.mp4')
    left_vid = cv2.VideoCapture(left_vid_path)
    right_vid = cv2.VideoCapture(right_vid_path)

    if two_masked:
        left_mask_vid_path = os.path.join(videos_dir, 'masked_regular_video_left.mp4')
        right_mask_vid_path = os.path.join(videos_dir, 'masked_regular_video_right.mp4')
        left_mask_vid = cv2.VideoCapture(left_mask_vid_path)
        right_mask_vid = cv2.VideoCapture(right_mask_vid_path)

    else:
        mask_vid_path = os.path.join(videos_dir, 'masked_video.mp4')
        mask_vid = cv2.VideoCapture(mask_vid_path)


    # for name in ["left_", "right_"]:
    #     for num in ["3", "4", "5", "7"]:
    #         img = cv2.imread(f"hands/{name+num}.jpg")
    #         get_table_corners(img, name=name+num, show=True)

    # waist frames from start
    if two_masked:
        _, mask_l = left_mask_vid.read();
        _, mask_r = right_mask_vid.read()
        _, mask_l = left_mask_vid.read();
        _, mask_r = right_mask_vid.read()
    else:
        _ = mask_vid.read();
        _, _ = mask_vid.read()

    _, _ = left_vid.read();
    _, _ = right_vid.read();
    _, _ = left_vid.read();
    _, _ = right_vid.read();
    # Capture first frame
    _, im_l = left_vid.read()
    _, im_r = right_vid.read()
    if two_masked:
        _, mask_l = left_mask_vid.read()
        _, mask_r = right_mask_vid.read()
        mask_l = cv2.resize(mask_l, (im_l.shape[1], im_l.shape[0]), interpolation=cv2.INTER_AREA)
        mask_r = cv2.resize(mask_r, (im_l.shape[1], im_l.shape[0]), interpolation=cv2.INTER_AREA)
        mask_l[mask_l < 230] = 0
        mask_l[mask_l >= 230] = 255
        mask_r[mask_r < 230] = 0
        mask_r[mask_r >= 230] = 255
    else:
        _, mask = mask_vid.read()
        mask[mask < 230] = 0
        mask[mask >= 230] = 255
        mask_l = mask[:, :mask.shape[1] // 2, 0]
        mask_r = mask[:, mask.shape[1] // 2:, 0]

    if use_right:
        im_l = im_r
        mask_l = mask_r

    corner_follower = CornersFollower(im_l, show=True)  # Create the follower

    times = []
    while True:  # play the video
        # Capture frame-by-frame
        ret1, im_l = left_vid.read()
        ret2, im_r = right_vid.read()
        if two_masked:
            r1, mask_l = left_mask_vid.read()
            r2, mask_r = right_mask_vid.read()
            ret3 = r1 and r2
        else:
            ret3, mask = mask_vid.read()

        if not (ret1 and ret2 and ret3):
            break

        if two_masked:
            mask_l = cv2.resize(mask_l, (im_l.shape[1], im_l.shape[0]), interpolation=cv2.INTER_AREA)[:, :, 0]
            mask_r = cv2.resize(mask_r, (im_l.shape[1], im_l.shape[0]), interpolation=cv2.INTER_AREA)[:, :, 0]
            mask_l[mask_l < 230] = 0
            mask_l[mask_l >= 230] = 255
            mask_r[mask_r < 230] = 0
            mask_r[mask_r >= 230] = 255
        else:
            mask[mask < 230] = 0
            mask[mask >= 230] = 255
            mask_l = mask[:, :mask.shape[1] // 2, 0]
            mask_r = mask[:, mask.shape[1] // 2:, 0]


        if use_right:
            im_l = im_r
            mask_l = mask_r

        # cv2.imshow("mask_l", mask_l)
        s = time.time()
        new_corners, changed = corner_follower.follow(im_l, mask_l, show=True, show_out=True)
        times.append(time.time() - s)

        if not changed:
            print("not changed")


        key = cv2.waitKey(100)
        if key == 27:
            break

    print(f"mean time: {np.mean(times)}")
    left_vid.release()
    right_vid.release()
    if two_masked:
        left_mask_vid.release()
        right_mask_vid.release()
    else:
        mask_vid.release()
