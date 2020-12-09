#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
# Ozer Ozkahraman (ozero@kth.se)

import rospy
import tf
import time
import math
import numpy as np

import common_globals
import imc_enums
import bb_enums

from geometry_msgs.msg import PointStamped, Pose, PoseArray
from geographic_msgs.msg import GeoPoint


class MissionPlan:
    def __init__(self,
                 plandb_msg,
                 plan_frame = 'utm',
                 waypoints=None,
                 waypoint_man_ids=None):
        """
        A container object to keep things related to the mission plan.
        """
        self.plandb_msg = plandb_msg
        self.plan_id = plandb_msg.plan_id
        self.plan_frame = plan_frame

        self.aborted = False

        # a list of names for each maneuver
        # good for feedback
        self.waypoint_man_ids = []

        # if waypoints are given directly, then skip reading the plandb message
        if waypoints is None:
            self.waypoints, self.waypoint_man_ids = self.read_plandb(plandb_msg)
        else:
            self.waypoints = waypoints
            self.waypoint_man_ids = waypoint_man_ids
            if self.waypoint_man_ids is None:
                self.waypoint_man_ids = []
                for i,wp in enumerate(self.waypoints):
                    self.waypoint_man_ids.append("Goto"+str(i+1))


        self.refined_waypoints = None

        # keep track of which waypoint we are going to
        self.current_wp_index = 0
        self.current_refined_wp_index = 0

        # used to report when the mission was received
        self.creation_time = time.time()


    @staticmethod
    def read_plandb(plandb):
        """
        planddb message is a bunch of nested objects,
        we want a list of waypoints in the local frame,
        """

        latlontoutm_service = rospy.ServiceProxy(self.latlontoutm_service_name,
                                                 GeoPoint)


        waypoints = []
        waypoint_man_ids = []
        request_id = plandb.request_id
        plan_id = plandb.plan_id
        plan_spec = plandb.plan_spec

        for plan_man in plan_spec.maneuvers:
            man_id = plan_man.maneuver_id
            man_name = plan_man.maneuver.maneuver_name
            man_imc_id = plan_man.maneuver.maneuver_imc_id
            maneuver = plan_man.maneuver
            # probably every maneuver has lat lon z in them, but just in case...
            if man_imc_id == imc_enums.MANEUVER_GOTO:
                try:
                    gp = GeoPoint()
                    gp.latitude = maneuver.lat
                    gp.longitude = maneuver.lon
                    # TODO check this
                    gp.altitude = -maneuver.z
                    utm_point = self.latlontoutm_service(gp)
                except rospy.service.ServiceException:
                    rospy.logerr_throttle_identical(5, "LatLon to UTM service failed! namespace:{}".format(self.latlontoutm_service_name))
                    return None, None

                waypoint = (utm_point.x, utm_point.y, maneuver.z)
                waypoints.append(waypoint)
                waypoint_man_ids.append(man_id)

            else:
                rospy.logwarn("SKIPPING UNIMPLEMENTED MANEUVER:", man_imc_id, man_name)

        return waypoints, waypoint_man_ids



    def get_pose_array(self, flip_z=False):
        pa = PoseArray()
        pa.header.frame_id = self.plan_frame

        # add the rest of the waypoints
        for wp in self.waypoints:
            p = Pose()
            p.position.x = wp[0]
            p.position.y = wp[1]
            if flip_z:
                p.position.z = -wp[2]
            else:
                p.position.z = wp[2]
            pa.poses.append(p)

        return pa


    def path_to_list(self, path_msg):
        frame = path_msg.header.frame_id
        if frame != '' and frame != self.plan_frame:
            rospy.logerr_throttle_identical(5, "Refined waypoints are not in "+self.plan_frame+" they are in "+frame+" !")
            return []

        wps = []
        for pose_stamped in path_msg.poses:
            wp = (
                pose_stamped.pose.position.x,
                pose_stamped.pose.position.y,
                pose_stamped.pose.position.z
            )
            wps.append(wp)
        return wps


    def __str__(self):
        s = ''
        for wp in self.waypoints:
            s += str(wp)+'\n'
        if self.refined_waypoints is not None:
            s += "with "+str(len(self.refined_waypoints))+" refined waypoints"
        return s


    def set_refined_waypoints(self, refined_waypoints):
        """
        given the waypoints in the plan, a path planner
        should create a more detailed and kinematically possible path
        to follow, we will keep that in this object too
        """
        self.refined_waypoints = refined_waypoints


    def is_complete(self):
        # check if we are 'done'
        if self.refined_waypoints is None:
            # not even refined, we are def. not done
            return False

        if self.current_refined_wp_index >= len(self.refined_waypoints) or \
           self.current_wp_index >= len(self.waypoints):
            # we went tru all wps, we're done
            return True

        return False


    def visit_wp(self):
        """ call this when you finish going to the wp"""
        if self.is_complete() or self.refined_waypoints is None:
            return

        ref_wp = self.refined_waypoints[self.current_refined_wp_index]
        coarse_wp = self.waypoints[self.current_wp_index]
        self.current_refined_wp_index += 1
        # check if the refined waypoint is close to a 'real' waypoint
        # if it is, we can count the 'real' wp as reached too
        diff = math.sqrt((ref_wp[0]-coarse_wp[0])**2 + (ref_wp[1]-coarse_wp[1])**2)
        if diff < common_globals.COARSE_PLAN_REFINED_PLAN_THRESHOLD:
            self.current_wp_index += 1


    def get_current_wp(self):
        """
        pop a wp from the remaining wps and return it
        """
        if self.is_complete() or self.refined_waypoints is None:
            return None
        ref_wp = self.refined_waypoints[self.current_refined_wp_index]
        return ref_wp, self.plan_frame



