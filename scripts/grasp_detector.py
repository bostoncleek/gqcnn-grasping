#!/usr/bin/env python3

# /*********************************************************************
#  * BSD 3-Clause License
#  *
#  * Copyright (c) 2020 PickNik LLC.
#  * All rights reserved.
#  *
#  * Redistribution and use in source and binary forms, with or without
#  * modification, are permitted provided that the following conditions are met:
#  *
#  *  * Redistributions of source code must retain the above copyright notice, this
#  *    list of conditions and the following disclaimer.
#  *
#  *  * Redistributions in binary form must reproduce the above copyright notice,
#  *    this list of conditions and the following disclaimer in the documentation
#  *    and/or other materials provided with the distribution.
#  *
#  *  * Neither the name of the copyright holder nor the names of its
#  *    contributors may be used to endorse or promote products derived from
#  *    this software without specific prior written permission.
#  *
#  * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
#  * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
#  * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
#  * DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
#  * FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
#  * DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
#  * SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
#  * CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
#  * OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
#  * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#  *********************************************************************/
#
# /* Author: Boston Cleek
#    Desc:   GQCNN- selects the grasp with the highest probability of success
# */


camera_intr_filename = "/home/bostoncleek/GPD_ws/src/gqcnn_demo/config/calib/camera.intr"
color_img_filename = "/home/bostoncleek/GPD_ws/src/gqcnn_demo/data/images/rgb_cylinder.png"
depth_img_filename = "/home/bostoncleek/GPD_ws/src/gqcnn_demo/data/images/depth_cylinder.png"

# color_img_filename = "/home/bostoncleek/GPD_ws/src/gqcnn_demo/data/images/rgb_clamp.png"
# depth_img_filename = "/home/bostoncleek/GPD_ws/src/gqcnn_demo/data/images/depth_clamp.png"

# color_img_filename = "/home/bostoncleek/GPD_ws/src/gqcnn_demo/data/images/rgb_berry.png"
# depth_img_filename = "/home/bostoncleek/GPD_ws/src/gqcnn_demo/data/images/depth_berry.png"

model_name = "GQCNN-4.0-PJ"
model_dir = "/home/bostoncleek/dex-net/deps/gqcnn/models/GQCNN-4.0-PJ"
config_filename = "/home/bostoncleek/dex-net/deps/gqcnn/cfg/examples/replication/dex-net_4.0_pj.yaml"

import json
import os
import sys
import time
import cv2
import numpy as np
from matplotlib import pyplot as plt

from autolab_core import YamlConfig, Logger
from perception import (BinaryImage, CameraIntrinsics, ColorImage, DepthImage,
                        RgbdImage)
from visualization import Visualizer2D as vis

from gqcnn.grasping import (RobustGraspingPolicy,
                            CrossEntropyRobustGraspingPolicy, RgbdImageState,
                            FullyConvolutionalGraspingPolicyParallelJaw,
                            FullyConvolutionalGraspingPolicySuction)
from gqcnn.utils import GripperMode


if __name__ == "__main__":

    # model weights
    model_config = json.load(open(os.path.join(model_dir, "config.json"), "r"))

    try:
        gqcnn_config = model_config["gqcnn"]
        gripper_mode = gqcnn_config["gripper_mode"]
    except KeyError:
        gqcnn_config = model_config["gqcnn_config"]
        input_data_mode = gqcnn_config["input_data_mode"]
        if input_data_mode == "tf_image":
            gripper_mode = GripperMode.LEGACY_PARALLEL_JAW
        elif input_data_mode == "tf_image_suction":
            gripper_mode = GripperMode.LEGACY_SUCTION
        elif input_data_mode == "suction":
            gripper_mode = GripperMode.SUCTION
        elif input_data_mode == "multi_suction":
            gripper_mode = GripperMode.MULTI_SUCTION
        elif input_data_mode == "parallel_jaw":
            gripper_mode = GripperMode.PARALLEL_JAW
        else:
            raise ValueError(
                "Input data mode {} not supported!".format(input_data_mode))

    # policy params
    config = YamlConfig(config_filename)
    policy_config = config["policy"]
    policy_config["metric"]["gqcnn_model"] = model_dir

    # # sensor
    camera_intr = CameraIntrinsics.load(camera_intr_filename)

    # images
    color_cvmat = cv2.imread(color_img_filename)
    depth_cvmat = cv2.imread(depth_img_filename) # load as 8UC3
    depth_cvmat = cv2.cvtColor(depth_cvmat, cv2.COLOR_BGR2GRAY) # 8UC1
    depth_cvmat = depth_cvmat.astype(np.float32) * 1.0/255.0 # 32FC1

    # cv2.imshow('img', color_cvmat)
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()

    # create wrapped BerkeleyAutomation/perception RGB and depth images
    color_im = ColorImage(color_cvmat, frame=camera_intr.frame, encoding="bgr8")
    depth_im = DepthImage(depth_cvmat, frame=camera_intr.frame)

    # check image sizes.
    if (color_im.height != depth_im.height or color_im.width != depth_im.width):
        msg = ("Color image and depth image must be the same shape! Color"
               " is %d x %d but depth is %d x %d") % (
                   color_im.height, color_im.width, depth_im.height,
                   depth_im.width)
        print(msg)

    # assume not mask is provided
    # segmask = depth_im.invalid_pixel_mask().inverse()
    segmask = BinaryImage(255 *
                          np.ones(depth_im.shape).astype(np.uint8),
                          frame=color_im.frame)

    # inpaint images.
    # color_im = color_im.inpaint(
    #     rescale_factor=config["inpaint_rescale_factor"])
    # depth_im = depth_im.inpaint(
    #     rescale_factor=config["inpaint_rescale_factor"])

    # Aggregate color and depth images into a single
    # BerkeleyAutomation/perception `RgbdImage`.
    rgbd_im = RgbdImage.from_color_and_depth(color_im, depth_im)

    state = RgbdImageState(rgbd_im, camera_intr, segmask=segmask)

    # vis.imshow(segmask)
    # vis.imshow(rgbd_im)
    # vis.show()

    policy = CrossEntropyRobustGraspingPolicy(policy_config)

    # Query policy.
    policy_start = time.time()
    action = policy(state)
    print("Planning took %.3f sec" % (time.time() - policy_start))

    print("Gripper pose: ", action.grasp.pose())

    # # Vis final grasp.
    if policy_config["vis"]["final_grasp"]:
        vis.figure(size=(10, 10))
        vis.imshow(rgbd_im.depth,
                   vmin=policy_config["vis"]["vmin"],
                   vmax=policy_config["vis"]["vmax"])
        vis.grasp(action.grasp, scale=2.5, show_center=False, show_axis=True)
        vis.title("Planned grasp at depth {0:.3f}m with Q={1:.3f}".format(
            action.grasp.depth, action.q_value))
        vis.show()

    # [x y z]
    # print("Position: ", action.grasp.pose().position)
    # [qw qx qy qz]
    # print("Orientation: ", action.grasp.pose().quaternion)
    # print("Frame: ", action.grasp.pose().to_frame)
    # print("Q value: ", action.q_value)


    # # cylinder
    # position = np.array([-4.57311577e-04, -1.43138524e-01, 5.06934174e-01])
    # orientation = np.array([ 0.4442379, 0.55013879, -0.4442379, 0.55013879])
    #
    # # strawberry
    # # position = np.array([-0.01649518,  0.0018328,   0.67722449])
    # # orientation = np.array([0.63906815,  0.30264155, -0.63906815,  0.30264155])
    #
    # frame = "camera_optical_link"
    # q_value = 0.0
    #
    # position = position.tolist()
    # orientation = orientation.tolist()
    #
    # # sys.stdout.flush()
    # sys.stdout.write(frame + '\n')
    # sys.stdout.write(str(position) + '\n')
    # sys.stdout.write(str(orientation) + '\n')
    # sys.stdout.write(str(q_value) + '\n')























#
