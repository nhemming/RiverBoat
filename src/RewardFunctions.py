"""
Holds a multitude of reward functions and a selector function that gives a reward function based on a user passed in
value

"""

# native packages
from abc import ABC, abstractmethod

# 3rd party packages

# own packages
import numpy as np


def select_reward_function(h_params, ao):
    """

    :param h_params: a dictionary that contains hyperparameters for the simulation
    :param ao: action operation used to convert raw outputs from a policy to actuator commands.
    :return: the reward function the simulation will use
    """

    # get the time step of the simulation
    delta_t = h_params['scenario']['time_step']

    # get the data specific to the reward function
    reward_info = h_params['reward_function']

    if reward_info['name'] == 'EveryStepForGettingCloserToGoal':

        crash_reward = reward_info['crash']
        success_reward = reward_info['success']

        reward_func = InstantStepCrashSuccessReward(delta_t, crash_reward, success_reward)

    elif reward_info['name'] == 'MultiStepCrashSuccessReward':

        refresh_rate = reward_info['agent_step_size']
        crash_reward = reward_info['crash']
        success_reward = reward_info['success']

        reward_func = MultiStepCrashSuccessReward(crash_reward, refresh_rate, success_reward)
    else:
        raise ValueError("The reward function selected is currently not supported. Please check the spelling or define a new function.")


    # check if reward is compatable with action operation


    return reward_func

class RewardFunction(ABC):

    def __init__(self, name):
        """
        base class for all reward functions to extend. Uses the new state information to determine if a reward is given
        to the agent and if the simulation has reached a terminating state.
        """
        self.name = name
        self.is_terminal = False
        self.is_crashed = False  # boolean for if the mover has crashed
        self.is_success = False  # boolean for if destination has been reached

    @abstractmethod
    def get_reward(self, t, mover_dict):
        """
        calculate the reward for the current step. Also set if teh simulation is completed.
        :param t: time
        :param mover_dict: dictionary containing all of the mover information
        :return:
        """
        pass

    @abstractmethod
    def reset(self, mover_dict):
        """
        reset any parameters that are maintained in the reward function

        :param mover_dict: a dictionary of mover information that has already been reset
        :return:
        """
        pass

    def get_terminal(self):
        """
        returns a boolean for if the goal state has been reached
        :return:
        """
        return self.is_terminal


class InstantStepCrashSuccessReward(RewardFunction):

    def __init__(self,delta_t, crash_reward, success_reward):
        """
        This reward only gives a reward for getting closer to the goal. The reward is proportional to the distance
        closed towards the destination. If the distance increases, no reward is given. If the boat is too close to
        another obstacle, the reward is negative.
        :param dest_dst the initial distance between the
        """
        super().__init__("RewardEveryStepForGettingCloserToGoal")

        self.delta_t = delta_t
        self.old_dst = None
        self.crash_reward = crash_reward
        self.success_reward = success_reward

    def get_reward(self, t, mover_dict):
        """
        calculate the reward for the current step. Also set if the simulation is completed.
        :param t: time
        :param mover_dict: dictionary containing all of the mover information
        :return:
        """

        self.is_crashed = False
        self.is_success = False

        reward = 0.0
        for name, mover in mover_dict.items():
            if mover.can_learn:
                # this is the river boat
                delta_range = self.old_dst - mover.state_dict['dest_dist']
                if delta_range >= 0:
                    # positive reward if boat got closer to the goal
                    reward += delta_range/(5.0*self.delta_t)

                self.old_dst = mover.state_dict['dest_dist']

                # TODO put this into the input file
                if mover.state_dict['dest_dist'] < 5.0:
                    self.is_terminal = True
                    self.is_success = True
                    reward += self.success_reward

                # check if crashed
                min_dst = np.infty
                for sensor in mover.sensors:
                    raw = sensor.get_raw_measurements()
                    raw_keys = raw.keys()
                    dst_key = [key for key in raw_keys if 'dist' in key][0]
                    if raw[dst_key] < min_dst:
                        min_dst = raw[dst_key]

                # check if minimum distance is less than size of any obstacles
                for tmp_name, tmp_mover in mover_dict.items():
                    if tmp_name != name:
                        # not the same mover. Calculations currently only support circle obstacles
                        if tmp_mover.state_dict['radius'] >= min_dst:
                            # boat has crashed
                            self.is_terminal = True
                            self.is_crashed = True
                            reward = self.crash_reward

        return reward

    def reset(self, mover_dict):
        """
        Reset the old distance so the reward function can determine if the step reduced the distance to the goal.
        :param mover_dict:
        :return:
        """

        for name, mover in mover_dict.items():
            if mover.can_learn:
                # updates sensors
                self.old_dst = mover.state_dict['dest_dist']

        # reset the flags for tracking states
        self.is_crashed = False
        self.is_success = False
        self.is_terminal = False

class MultiStepReward(RewardFunction):

    def __init__(self, name, refresh_rate):
        """
        This is the base class for reward functions that do not operate over only one simulation time step.
        :param name: the name of the reward, usefull in debugging
        :param refresh_rate: the rate at which cummulative reward is calculated.
        """
        super().__init__(name)
        self.refresh_rate = refresh_rate
        self.last_reward_time = 0.0
        self.cumulative_reward = 0.0

class MultiStepCrashSuccessReward(MultiStepReward):

    def __init__(self, crash_reward, refresh_rate, success_reward):
        super().__init__(name='MultiStepCrashSuccessReward', refresh_rate=refresh_rate)

        self.crash_reward = crash_reward
        self.success_reward = success_reward

    def get_reward(self, t, mover_dict):
        """
        calculate the reward for the current step. Also set if the simulation is completed.
        :param t: time
        :param mover_dict: dictionary containing all of the mover information
        :return:
        """
        self.is_crashed = False
        self.is_success = False

        for name, mover in mover_dict.items():
            if mover.can_learn:
                # this is the river boat
                delta_range = self.old_dst - mover.state_dict['dest_dst']
                if delta_range >= 0:
                    # positive reward if boat got closer to the goal
                    self.cumulative_reward += delta_range / (5.0 * self.delta_t)

                self.old_dst = mover.state_dict['dest_dst']

                # TODO put this into the input file
                if mover.state_dict['dest_dst'] < 5.0:
                    self.is_terminal = True
                    self.cumulative_reward += self.success_reward

                # check if crashed
                min_dst = np.infty
                sensors = mover.get_sensors()
                for sensor in sensors:
                    raw = sensor.get_raw_measurements()
                    raw_keys = raw.keys()
                    dst_key = [key for key in raw_keys if 'dest' in key][0]
                    if raw[dst_key] < min_dst:
                        min_dst = raw[dst_key]

                # check if minimum distance is less than size of any obstacles
                for tmp_name, tmp_mover in mover_dict.items():
                    if tmp_name != name:
                        # not the same mover. Calculations currently only support circle obstacles
                        if tmp_mover.state_dict['radius'] >= min_dst:
                            # boat has crashed
                            self.is_terminal = True
                            self.is_crashed = True
                            self.cumulative_reward += self.crash_reward


        # check if the agent step has fully taken place
        reward = 0.0
        if (t-self.last_reward_time) >= self.refresh_rate:

            # reset step tracking information
            self.last_reward_time = t
            reward = self.cumulative_reward
            self.cumulative_reward = 0.0

        return reward
