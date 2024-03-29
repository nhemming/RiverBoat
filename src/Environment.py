"""
Is a class for holding the simulation environment. Specific simualations can be built on top of the base simulation

"""

# native packages
from abc import ABC, abstractmethod
from collections import namedtuple
from collections import OrderedDict
import os

# 3rd party packages
import numpy as np
import pandas as pd
import torch
import yaml

# own packages
import src.ActionOperation as ActionOperation
import src.Controller as Controller
import src.LearningAlgorithms as LearningAlgorithms
import src.Movers as Movers
import src.ReplayMemory as ReplayMemory
import src.RewardFunctions as RewardFunctions
import src.Sensors as Sensors


class Environment(ABC):

    def __init__(self, h_params):
        self.h_params = h_params
        self.mover_dict = OrderedDict()
        self.agent = None  # learning agent
        self.ao = None  # action operation. Used to convert raw outputs to inputs
        self.reward_func = None  # reward function for the simulation
        self.device = 'cuda' # TODO need to check this
        self.header = ['time', 'reward', 'is_terminal', 'is_crashed', 'is_reached', 'destination_x','destination_y'] # history data frame header
        self.history = None  # eventually a data frame to hold information about the simulation
        self.evaluation_info = None  # dictionary used for setting the initial conditions of evaluation episodes.
        self.n_evaluations = 0  # the size of the evaluation episode set.
        self.destination = None  # point in space for the destination of the boat (x,y) [m]

    #@abstractmethod
    def reset_environment(self, reset_to_max_power):
        """
        generates a random initial state for the simulaiton.
        :return:
        """

        domain = self.h_params['scenario']['domain']

        # set a random initial location for the destination
        x = np.random.random() * domain
        y = np.random.random() * domain
        self.destination = [x,y]

        # set up random locations and orientations for the movers
        for name, mover in self.mover_dict.items():

            if 'river_boat' in name:

                # whipe state to base configuration for the boat
                mover.initalize_in_state_dict()

                # reset the river boats data
                dst_to_dest = 0.0

                while dst_to_dest <= 30.0:
                    mover.state_dict['x_pos'] = np.random.random() * domain
                    mover.state_dict['y_pos'] = np.random.random() * domain
                    dst_to_dest = np.sqrt((mover.state_dict['x_pos'] - self.destination[0]) ** 2 + (
                                mover.state_dict['y_pos'] - self.destination[1]) ** 2)

                mover.state_dict['psi'] = np.random.random() * 2.0*np.pi
                tmp_delta = (np.random.random()-0.5)*2.0*np.abs(mover.state_dict['delta_max'][0])

                # reset the velocities of the boat
                mover.state_dict['v_xp'] = np.random.random()
                mover.state_dict['v_yp'] = np.random.random()-0.5
                mover.state_dict['psi_dot'] = 0.0 #(np.random.random()-0.5)/10.0

                mover.state_dict['v_x'] = mover.state_dict['v_xp'] * np.cos(-mover.state_dict['psi']) + mover.state_dict[
                    'v_yp'] * np.sin(-mover.state_dict['psi'])
                mover.state_dict['v_y'] = -mover.state_dict['v_xp'] * np.sin(-mover.state_dict['psi']) + mover.state_dict[
                    'v_yp'] * np.cos(-mover.state_dict['psi'])

                # power setting needs to be set from action designation.
                if reset_to_max_power:
                    tmp_power = mover.state_dict['power_max']
                else:
                    tmp_power = np.random.random()*mover.state_dict['power_max']

                mover.set_control(tmp_power, tmp_delta)

                # reset the fuel on the boat
                mover.state_dict['fuel'] = mover.state_dict['fuel_capacity']


            elif 'static_circle' in name:
                # reset the static circle
                max_dst_to_other = 0.0
                dst_to_dest = 0.0
                while dst_to_dest <= mover.state_dict['radius']*2.0 and max_dst_to_other <= mover.state_dict['radius']*2.0:
                    # draw random positions for the obstacle until it is not too close to the goal location or any other
                    # movers

                    mover.state_dict['x_pos'] = np.random.random()*domain
                    mover.state_dict['y_pos'] = np.random.random() * domain
                    dst_to_dest = np.sqrt( (mover.state_dict['x_pos']-self.destination[0])**2 + (mover.state_dict['y_pos']-self.destination[1])**2)

                    max_dst_to_other = np.infty

                    for tmp_name, tmp_mover in self.mover_dict.items():
                        if tmp_name != name:
                            # other obstacle selected in the loop
                            x_other = tmp_mover.state_dict['x_pos']
                            y_other = tmp_mover.state_dict['y_pos']
                            tmp_dst = np.sqrt((mover.state_dict['x_pos']-x_other)**2 + (mover.state_dict['y_pos']-y_other)**2)
                            if tmp_dst < max_dst_to_other:
                                max_dst_to_other = tmp_dst
            else:
                raise ValueError('Mover not currently supported')

        # updates sensors
        for name, mover in self.mover_dict.items():
            mover.update_sensors(self.mover_dict)
            mover.derived_measurements(self.destination)

        # reset reward function information
        self.reward_func.reset(self.mover_dict)

        # reset the action operation
        self.ao.reset()

    #@abstractmethod
    def reset_evaluation_environment(self, row_idx, reset_to_max_power):

        # reset the destination
        self.destination = [self.evaluation_info['destination_x'].iloc[row_idx], self.evaluation_info['destination_y'].iloc[row_idx]]

        # reset the mover initial values
        # set up random locations and orientations for the movers
        for name, mover in self.mover_dict.items():

            if 'river_boat' in name:

                # whipe state to base configuration for the boat
                mover.initalize_in_state_dict()

                # loop through reset items
                for i, variable in enumerate(self.evaluation_info.columns):

                    if 'river_boat' in variable:
                        var_mover = variable.split('-')[1]
                        mover.state_dict[var_mover] = self.evaluation_info[variable].iloc[row_idx]


                mover.state_dict['v_x'] = mover.state_dict['v_xp'] * np.cos(-mover.state_dict['psi']) + \
                                          mover.state_dict[
                                              'v_yp'] * np.sin(-mover.state_dict['psi'])
                mover.state_dict['v_y'] = -mover.state_dict['v_xp'] * np.sin(-mover.state_dict['psi']) + \
                                          mover.state_dict[
                                              'v_yp'] * np.cos(-mover.state_dict['psi'])

                # power setting needs to be set from action designation.
                if reset_to_max_power:
                    tmp_power = mover.state_dict['power_max']
                else:
                    tmp_power = np.random.random() * mover.state_dict['power_max']

                mover.set_control(tmp_power, mover.state_dict['delta'])

                # reset the fuel on the boat
                mover.state_dict['fuel'] = mover.state_dict['fuel_capacity']

            elif 'static_circle' in name:
                # reset the static circle

                # loop through reset items
                for i, variable in enumerate(self.evaluation_info.columns):

                    if 'static_circle' in variable:
                        var = variable.split("-")[1]
                        mover.state_dict[var] = self.evaluation_info[variable].iloc[row_idx]
            else:
                raise ValueError('Mover not currently supported')

        # updates sensors
        for name, mover in self.mover_dict.items():
            mover.update_sensors(self.mover_dict)
            mover.derived_measurements(self.destination)

        # reset reward function information
        self.reward_func.reset(self.mover_dict)

        # reset the action operation
        self.ao.reset()


    def add_mover(self, mover):
        """
        adds a mover to all of the movers in the simulation. The collection of movers are what are updated through time

        :param mover:
        :return:
        """
        if isinstance(mover,Movers.Mover):
            name = mover.state_dict['name']
            self.mover_dict[name] = mover
        else:
            raise ValueError('Added mover must be of type mover')

    def run_simulation(self, ep_num, is_evaluation, reset_to_max_power, evaluation_number=0):
        """

        :param is_baseline: a boolean for if the episode being run is a baseline episode or a training episode is being
            run
        :param ep_num: the episode number in the training
        :return:
        """


        # reset environment
        if is_evaluation:
            # reset the initial conditions
            self.reset_evaluation_environment(evaluation_number, reset_to_max_power)
        else:
            self.reset_environment(reset_to_max_power)


        # reset the reward function
        self.reward_func.reset(self.mover_dict)

        # reset the time stamps of the
        step_num = 0
        t = 0.0
        delta_t = self.h_params['scenario']['time_step']
        max_t = float(self.h_params['scenario']['max_time'])
        max_steps = int(np.ceil(max_t / delta_t))
        if is_evaluation:
            # if the simulation is an evaluation simulation, allow for more simulation time. Here the consecrn is how
            # well the agent completes its objective not how fast.
            max_steps *= 2

        # reset history of the movers
        for name, mover in self.mover_dict.items():
            mover.reset_history(max_steps)

        # reset own history
        self.history = pd.DataFrame(data=np.zeros(((max_steps), len(self.header))),columns=self.header)

        # holding the state prior to a step. Initialized as none so the loop knows to use the first state as its state
        reset_state = True
        reward = 0.0
        cumulative_reward = 0.0
        min_dst = np.infty  # the minimum distance of the boat to the goal
        # boolean for if the agent has reached a terminal state prior to the end of the episode
        is_terminal = False
        end_step = False  # if this is true the agent will know to log the data and make another prediction
        while step_num < max_steps and not is_terminal:

            # step the simulation
            interim_state, interim_org_action, interim_used_action, interim_path_cps, interim_critic_vals, interim_reward, interim_next_state, end_step, is_terminal, is_crashed, is_success, curr_dist = self.step(ep_num, t, end_step, is_evaluation)

            # the non-dimensional values of the state
            # org_action - action before exmplation is added
            # used_action - action where exploration may or may not be used. THis is the action used for the MDP
            # path_cps - a list of path control points that define the naviation path. This is none for direct contol methods
            # critic values - q values or the critics outpput values
            # reward - given rewared during the simualtion step
            # next_state - non-dimensional state after the movers moved
            # end_step - if teh agents step completed or not. Should always be true for direct control and periodically true for path control
            # is_terminal - if the simulation is done
            # is_crashed - boolean if the boat crashed into an obstacle
            # is_success - of the simulation ended reaching its goal
            # dest_dst - distance to the destination after stepping
            #return state, org_action, used_action, path_cps, critic_values, reward, next_state, end_step, is_terminal, self.reward_func.is_crashed, self.reward_func.is_success, dest_dst

            # check if the distance is closer than any previous distances. If so save the distance
            if curr_dist < min_dst:
                min_dst = curr_dist

            # if the state is empty update it to the interim state
            if reset_state:
                state = interim_state
                org_action = interim_org_action
                action = interim_used_action
                path_cps = interim_path_cps
                critic_vals = interim_critic_vals
                reward = interim_reward
                reset_state = False

            if end_step or is_terminal:
                # add data to memory because the agents step has completed.
                next_state = interim_next_state
                reward = interim_reward

                # convert the tuple to tensors
                state_tensor = ReplayMemory.convert_numpy_to_tensor(self.device,list(state.values()))
                next_state_tensor = ReplayMemory.convert_numpy_to_tensor(self.device, list(next_state.values()))

                if type(action) == list:
                    action_tensor = ReplayMemory.convert_numpy_to_tensor(self.device, action)
                else:
                    action_tensor = ReplayMemory.convert_numpy_to_tensor(self.device, [action])
                #reward_tensor = torch.tensor([reward]).to(self.device)
                reward_tensor = ReplayMemory.convert_numpy_to_tensor(self.device, [reward])
                #is_terminal_tensor = torch.tensor([is_terminal]).to(self.device)
                is_terminal_tensor = ReplayMemory.convert_numpy_to_tensor(self.device, [is_terminal])

                # store the data
                if not is_evaluation:
                    if self.replay_storage.strategy == 'outcome':
                        outcome = 'other'
                        if is_crashed:
                            outcome = 'crash'
                        elif is_success:
                            outcome = 'success'

                        self.replay_storage.push(state_tensor,action_tensor,next_state_tensor,reward_tensor,is_terminal_tensor, outcome)
                    else:
                        self.replay_storage.push(state_tensor,action_tensor,next_state_tensor,reward_tensor,is_terminal_tensor)

                # reset the state to None for the agents next step
                reset_state = True
            else:
                reward += interim_reward

            # add history of the movers the simulation
            for name, mover in self.mover_dict.items():
                mover.add_step_history(step_num)

            # add simulation specific history
            org_action = interim_org_action
            action = interim_used_action
            path_cps = interim_path_cps
            critic_vals = interim_critic_vals

            if type(org_action) != list and not isinstance(org_action,np.ndarray):
                org_action = [org_action]
            if type(action) != list and not isinstance(org_action,np.ndarray):
                action = [action]

            telemetry = np.concatenate(([t, reward, is_terminal, is_crashed, is_success,
                                         self.destination[0], self.destination[1]],org_action,action,path_cps,critic_vals))
            self.history.iloc[step_num] = telemetry

            # add simulation specific data from the learner. destination distance

            t += delta_t
            step_num += 1
            cumulative_reward += interim_reward

        # trim the history
        self.history.drop(range(step_num, len(self.history)), inplace=True)
        for name, mover in self.mover_dict.items():
            mover.trim_history(step_num)

        # sort the stored data into buffers as needed
        if not is_evaluation:
            self.replay_storage.sort_data_into_buffers()

        return cumulative_reward, is_crashed, is_success, min_dst, t

    def write_history(self, ep_num, is_evaluation, eval_num=0):
        """
        writes the histories of the movers and the simulation out for later analysis
        :return:
        """

        total_history = self.history

        for name, mover in self.mover_dict.items():

            # get mover files
            tmp_histroy = mover.history

            # add history together
            total_history = pd.concat([total_history, tmp_histroy], axis=1)

        # write total history out to a file
        if is_evaluation:
            file_name = 'Output//' + str(self.h_params['scenario']['experiment_set']) + '//' + str(
                self.h_params['scenario']['trial_num']) + '//Evaluation//Data//History_' + str(ep_num) + '-'+str(eval_num)+'.csv'
            total_history.to_csv(file_name, index=False)
        else:
            if self.save_training_data and ep_num % self.save_freq == 0:
                # only save the data to a csv if it is allowed and the episode number matches the goal. Ideally all of
                # the data is saved, but there is no more room on my computer
                file_name = 'Output//' + str(self.h_params['scenario']['experiment_set'])+ '//' + str(self.h_params['scenario']['trial_num'])+'//TrainingHistory//Data//History_'+str(ep_num)+'.csv'
                total_history.to_csv(file_name, index=False)

    def step(self, ep_num, t, end_step, is_evaluation):
        """
        steps the simulation one time step. The agent is given a normalized state to make an action selection. Then
        the action is operated on the environment

        :param t:  time of the simulation [s]
        :return:
        """

        # updates sensors
        for name, mover in self.mover_dict.items():
            mover.update_sensors(self.mover_dict)
            mover.derived_measurements(self.destination)

        # step movers
        for name, mover in self.mover_dict.items():
            if mover.can_learn:
                # this mover is an agent and not a deterministic entity

                # normalize the state
                keys = mover.observation_df['name']
                dimensional_values = OrderedDict()
                non_dimensional_values = OrderedDict()
                for key in keys:
                    dimensional_values[key] = mover.state_dict.get(key)
                    non_dimensional_values[key] = mover.state_dict.get(key)

                norm_values = mover.observation_df['norm_value'].to_numpy()
                norm_methods = mover.observation_df['norm_method'].to_numpy()
                for i, norm_strat in enumerate(norm_values):
                    # TODO norm by strategy. MOve this to its own method
                    non_dimensional_values[keys[i]] = dimensional_values[keys[i]]/norm_values[i]

                # add the normalized sensor measurements
                for sensor in mover.sensors:
                    norm_meas = sensor.get_norm_measurements()
                    non_dimensional_values.update(norm_meas)

                # get the action and network outputs from the network
                inp = list(non_dimensional_values.values())

                # raw_outputs - q values or actor values
                # critic values - either the q values or the critics values
                raw_ouputs, critic_values = self.agent.get_output(inp)
                critic_values = critic_values.cpu().detach().numpy()[0]

                # convert the action to a command change
                #propeller_angle_change, power_change, action, action_meta_data, end_step = self.ao.action_to_command(ep_num, t, mover.state_dict, raw_ouputs)

                # propeller_angle_change - the amount to change the propeller angle relative to current position [rad]
                # power_change - the amount of power to change being deliverd to the propeller [watt]
                # org_action - the original action produced without exploration being added
                # used_action - the action that may or may not have exploration added to it. THis is what is used for the simulation to step
                # path_cps - if a path is used, this is a list of control points that define the path. Else it is false
                # end_step - if this is the end of an agent step
                propeller_angle_change, power_change, org_action, used_action, path_cps, end_step = self.ao.action_to_command(ep_num, t, mover.state_dict, raw_ouputs, is_evaluation)

                # apply the actuator changes to the mover
                power = power_change + mover.state_dict['power']
                propeller_angle = propeller_angle_change + mover.state_dict['delta']
                mover.set_control(power,propeller_angle)

            mover.step(time=t)

        # save the original state before stepping
        state = non_dimensional_values

        # normalize the state prime
        for name, mover in self.mover_dict.items():
            mover.update_sensors(self.mover_dict)
            mover.derived_measurements(self.destination)

        for name, mover in self.mover_dict.items():
            if mover.can_learn:
                # this mover is an agent and not a deterministic entity

                # normalize the state
                keys = mover.observation_df['name']
                dimensional_values = OrderedDict()
                non_dimensional_values = OrderedDict()
                for key in keys:
                    dimensional_values[key] = mover.state_dict.get(key)
                    non_dimensional_values[key] = mover.state_dict.get(key)

                norm_values = mover.observation_df['norm_value'].to_numpy()
                norm_methods = mover.observation_df['norm_method'].to_numpy()
                for i, norm_strat in enumerate(norm_values):
                    # TODO norm by strategy. MOve this to its own method
                    non_dimensional_values[keys[i]] = dimensional_values[keys[i]]/norm_values[i]

                # add the normalized sensor measurements
                for sensor in mover.sensors:
                    norm_meas = sensor.get_norm_measurements()
                    non_dimensional_values.update(norm_meas)

        next_state = non_dimensional_values

        # get the reward
        reward = self.reward_func.get_reward(t, self.mover_dict)

        # get if the simulation has reach a termination condition
        is_terminal = self.reward_func.get_terminal()

        # get the distance to the destination
        for name, mover in self.mover_dict.items():
            if mover.can_learn:
                # updates sensors
                dest_dst = mover.state_dict['dest_dist']

        # the non-dimensional values of the state
        # org_action - action before exmplation is added
        # used_action - action where exploration may or may not be used. THis is the action used for the MDP
        # path_cps - a list of path control points that define the naviation path. This is none for direct contol methods
        # critic values - q values or the critics outpput values
        # reward - given rewared during the simualtion step
        # next_state - non-dimensional state after the movers moved
        # end_step - if teh agents step completed or not. Should always be true for direct control and periodically true for path control
        # is_terminal - if the simulation is done
        # is_crashed - boolean if the boat crashed into an obstacle
        # is_success - of the simulation ended reaching its goal
        # dest_dst - distance to the destination after stepping
        return state, org_action, used_action, path_cps, critic_values, reward, next_state, end_step, is_terminal, self.reward_func.is_crashed, self.reward_func.is_success, dest_dst

    def launch_training(self):
        """
        starts training. It either picks up where a previous training was stopped or ended, or
        it starts training from scratch. A dictionary in the environment class called 'h_params'
        holds all of the training parameters and settings. That can be loaded in the
        'create_environment' method. Data is regularly saved out from the training
        and simulations so the experimenter can analyze the results and check on the
        progress.

        :return:
        """

        if self.h_params['scenario']['continue_learning']:
            # load info and prepare simulation from old training to continue training
            pass

            # TODO implement

        else:
            # looking to start a training from scratch

            # check if data already exists for this scenario
            if os.path.exists("Output/"+str(self.h_params['scenario']['experiment_set'])):
                # check if trial number is there
                if os.path.exists("Output/"+str(self.h_params['scenario']['experiment_set'])+"/"+str(self.h_params['scenario']['trial_num'])):
                    overwrite_data = input("Data already exists for the experiment set and trial number. Do you want to overwrite the data [y/n]? ")

                    if overwrite_data != 'y':
                        return

            self.create_folders()

        # save a copy of the hyperparameters
        self.save_hparams()

        # add agents/entities to the simulation. Boats, and obstacles
        self.add_entities()

        # load in the senors
        sensors = self.add_sensors()

        # get the controller
        controller = self.get_controller()

        # get the action determination
        # this is an ugly hack. TODO come up with a more clean method. May need to change where the history header is defined
        if self.h_params['learning_algorithm']['name'] == 'DQN':
            n_critic_outputs = None
        else:
            n_critic_outputs = 1
        action_size, self.ao, reset_to_max_power = self.get_action_size_and_operation(controller, n_critic_outputs)

        # get the state size
        state_size = self.get_state_size()

        # temporary for when only using one agent
        #if len(state_size) != 1:
        #    raise ValueError('Only single agent learning currently supported')

        # get the learning algorithm
        la = self.get_learning_algorithm(action_size,state_size, self.h_params['optimizer'])
        self.agent = la

        # get the reward function
        self.reward_func = RewardFunctions.select_reward_function(self.h_params, self.ao)

        # get the replay buffer
        self.get_memory_mechanism()

        # parse the evaluation data
        self.get_evaluation_information()

        # set data storage parameters
        self.set_data_storage()

        # loop over training
        elapsed_episodes = 0
        num_episodes = self.h_params['scenario']['num_episodes']

        # write the header for overall training progress
        progress_file_name = "Output/" + str(self.h_params['scenario']['experiment_set']) + "/" + str(
                               self.h_params['scenario']['trial_num'])+"/Progress/Data/training_progress.csv"
        with open(progress_file_name, 'w') as f:
            f.write('ep_num,cumulative_reward,is_crashed,is_success,min_dst,simulation_time\n')
            f.flush()

        while elapsed_episodes < num_episodes:

            # check if evaluation episodes are to be rn


            if elapsed_episodes % self.h_params['scenario']['evaluation_frequency'] == 0 or elapsed_episodes == 0:
                # run a suite of evaluation episodes
                self.run_evaluation_set(elapsed_episodes, reset_to_max_power)


            # run the episode where training data is accumulated
            cumulative_reward, is_crashed, is_success, min_dst, total_episode_time = self.run_simulation(elapsed_episodes,is_evaluation=False, reset_to_max_power=reset_to_max_power)

            print("Episode Number={}\tSuccess={}\tCrash={}\tProximity={:.3f}\tReward={:.3f}".format(elapsed_episodes, is_success, is_crashed,min_dst,
                                                                                 cumulative_reward))

            # write episode history out to a file
            self.write_history(elapsed_episodes,is_evaluation=False)

            # save macro simulation information
            with open(progress_file_name, 'a') as f:
                f.write(str(elapsed_episodes)+','+str(cumulative_reward)+','+str(is_crashed)+','+str(is_success)+','+str(min_dst)+','+str(total_episode_time)+'\n')
                f.flush()

            # train the networks
            self.agent.train_agent(self.replay_storage)

            # update target networks if applicable
            if elapsed_episodes > 0 and elapsed_episodes % self.h_params['learning_algorithm']['target_frequency'] == 0:

                # update the target networks parameters
                #self.agent.target_network.load_state_dict(self.agent.network.state_dict())
                self.agent.update_target_network()

                # save the networks
                self.agent.save_networks(elapsed_episodes,"Output/" + str(self.h_params['scenario']['experiment_set']) + "/" + str(
                               self.h_params['scenario']['trial_num'])+"/Models/")

            elapsed_episodes += 1

    def create_folders(self):
        """
        creates all of the sub folders that are needed for the training to save data to.
        Training progress, simulation telemetry, and models are all saved for later use
        and analysis.

        :return:  void
        """

        # create base folder
        try:
            os.mkdir("Output/" + str(self.h_params['scenario']['experiment_set']))
        except:
            pass

        # create trial folder
        try:
            os.mkdir("Output/"+str(self.h_params['scenario']['experiment_set'])+"/"+str(self.h_params['scenario']['trial_num']))
        except:
            pass

        # create sub folders
        sub_folder_names = ["\Models","\TrainingHistory","\TrainingHistory\Data","\TrainingHistory\Graphs","\TrainingHistory\Videos",
                            "\Evaluation","\Evaluation\Data","\Evaluation\Graphs","\Evaluation\Videos",
                            #"\EvaluationBaseline", "\EvaluationBaseline\Data", "\EvaluationBaseline\Graphs",
                            "\Progress","\Progress\Data","\Progress\Graphs"]
        for sfn in sub_folder_names:
            try:
                os.mkdir("Output/"+str(self.h_params['scenario']['experiment_set'])+"/"+str(self.h_params['scenario']['trial_num'])+sfn)
            except:
                pass

        # create initial info file for the user to type to help document the trial
        new_file = True
        if os.path.exists("Output/"+str(self.h_params['scenario']['experiment_set'])+"/"+str(self.h_params['scenario']['trial_num'])+'notes.txt'):
            overwrite_notes = input("Do you want to overwrite the notes file [y/n]?")

            if overwrite_notes != 'y':
                new_file = False

        if new_file:
            with open("Output/"+str(self.h_params['scenario']['experiment_set'])+"/"+str(self.h_params['scenario']['trial_num'])+'/notes.txt', 'w') as f:

                f.write("TODO, the user should add some comments about the reason for this scenario and about some of the "
                        "findings from this trial. This will help for compiling results.")

    def add_sensors(self):
        """
        creates sensor objects for all of the sensors defined in the input file. The sensors can then be installed into
        movers/agents

        :return: none
        """

        try:
            sensors_data = self.h_params['sensors']

            for name, sensor in sensors_data.items():

                if 'lidar_' in name:
                    # create a ProcessedLidar object that simulates the measurements after the raw lidar data has been
                    # filtered and obstacles more succintly defined

                    measurement_df = pd.DataFrame(columns=['name','norm_value','norm_method'])
                    meas_var_info = sensor['max_range']
                    meas_var_info = meas_var_info.split(',')
                    row = dict()
                    row['name'] = 'max_range'
                    row['norm_value'] = float(meas_var_info[1])
                    row['norm_method'] = meas_var_info[2]
                    measurement_df = measurement_df.append(row, ignore_index=True)

                    meas_var_info = sensor['max_theta']
                    meas_var_info = meas_var_info.split(',')
                    row = dict()
                    row['name'] = 'max_theta'
                    row['norm_value'] = float(meas_var_info[1])
                    row['norm_method'] = meas_var_info[2]
                    measurement_df = measurement_df.append(row, ignore_index=True)

                    tmp_sensor = Sensors.ProcessedLidar(base_range=float(sensor['base_range']),base_theta=float(sensor['base_theta']),
                                           name=name,measurement_norm_df=measurement_df,mover_owner_name=sensor['install_on'])

                    for mover_name, mover in self.mover_dict.items():
                        if mover_name == tmp_sensor.mover_owner_name:
                            mover.add_sensor(tmp_sensor)

                            # add the data from the sensor to the history for the mover
                            tmp_state = tmp_sensor.get_raw_measurements()
                            for ts in tmp_state:
                                mover.history_header.append(mover.state_dict['name'] + '_' + ts)

                else:
                    raise ValueError('Sensor not currently supported')
        except:
            pass

    def add_entities(self):
        """
        Adds movers and obstacles to the simulation to run

        :return:
        """
        movers = self.h_params['movers']
        delta_t = self.h_params['scenario']['time_step']
        for name, mover_details in movers.items():

            if 'river_boat' in name:
                # create a river boat mover and add it to the mover dictionary
                tmp_mover = Movers.RiverBoat.create_from_yaml(name,mover_details, delta_t)
            elif 'static_circle' in name:
                # create a circle obstacle that does not move
                tmp_mover = Movers.StaticCircleObstacle.create_from_yaml(name,mover_details)
            else:
                raise ValueError('Mover type ' + name + ' not currently supported')

            self.add_mover(tmp_mover)

    def get_controller(self):
        """
        the controller coeffiecints from the input file are loaded so the boat can use it.
        Currently only, a pd controller is supported.

        :return: the controller object
        """
        controller_info = self.h_params['controller']
        if controller_info['type'] == 'pd':
            coeffs_lst = controller_info['coeffs'].split(',')
            coeffs = namedtuple("Coeffs", "p d")
            pd_coeffs = coeffs(coeffs_lst[0], coeffs_lst[1])
            controller = Controller.PDController(coeffs=pd_coeffs, is_clipped=False, max_change=np.pi)
        else:
            raise ValueError('Controller type not currently supported')

        return controller

    def get_action_size_and_operation(self, controller, n_critic_outputs):
        """
        from the input file, get the action formulation specified by the user. The action specification dictates how
        an action is split. For example, are control points used to build a path, are a set of canned paths used, or
        is direct control of the actuators used. The output then is the action formulation object and the number
        of outputs a neural network will need. The action operation is also used during the simuliation to convert
        raw neural network outputs to actuator control changes.

        :param controller: the controller used by the boat. This can be None if the neural network is directly
            controlling the actuators.
        :param n_critic_outputs: the number of output values from the critic network
        :return: the number of actions a neural network needs to predict, and the action operation object that converts
            neural network outputs to actuator control changes.
        """
        action_type = self.h_params['action_description']['action_type']
        action_designation = self.h_params['action_description']['action_designation']
        ao = None

        if action_type == 'continous' and action_designation == 'control_point':
            # use continously defined control points to define a b-spline path

            #  name, replan_rate,controller, angle_range, power_range=None, num_control_point=4, epsilon_schedule=None, segment_length=10
            ao = ActionOperation.PathContinousCp(name='discrete_cp',
                                                replan_rate=self.h_params['action_description']['replan_rate'],
                                                controller=controller,
                                                angle_range=self.h_params['action_description']['angle_range'],
                                                action_sigma=self.h_params['action_description']['action_sigma'],
                                                power_range=self.h_params['action_description']['power_range'],
                                                 num_control_point=2,
                                                 epsilon_schedule=self.h_params['action_description']['eps_schedule'],
                                                 segment_length=self.h_params['action_description']['segment_length'])
        elif action_type == 'continous' and action_designation == 'direct':
            # agent is directly controlling the actuators with discrete choices
            ao = ActionOperation.DirectControlActionContinous(name='discrete_direct',
                                                             max_propeller=self.h_params['learning_algorithm'][
                                                                 'max_action'],
                                                             max_power=self.h_params['action_description'][
                                                                 'max_power'],
                                                              action_sigma=self.h_params['action_description']['action_sigma'],
                                                              epsilon_schedule=self.h_params['action_description']['eps_schedule'])
        elif action_type == 'discrete' and action_designation == 'canned':
            # used discrete canned paths
            ao = ActionOperation.PathDiscreteCanned(name='canned_cp',replan_rate=self.h_params['action_description']['replan_rate'],
                                                controller=controller,
                                                turn_amount_lst=self.h_params['action_description']['turn_values'],
                                                s_curve_lst=self.h_params['action_description']['s_curve_values'],
                                                power_change_lst=self.h_params['action_description']['power_values'])
        elif action_type == 'discrete' and action_designation == 'control_point':
            # use disrete CP action type
            ao = ActionOperation.PathDiscreteCp(name='discrete_cp',
                                                replan_rate=self.h_params['action_description']['replan_rate'],
                                                controller=controller,
                                                angle_adj_lst=self.h_params['action_description']['angle_values'],
                                                power_change_lst=self.h_params['action_description']['power_values'],
                                                epsilon_schedule=self.h_params['action_description']['eps_schedule'],
                                                segment_length=self.h_params['action_description']['segment_length'])

        elif action_type == 'discrete' and action_designation == 'direct':
            # agent is directly controlling the actuators with discrete choices
            ao = ActionOperation.DirectControlActionDiscrete(name='discrete_direct',
                                                prop_change_angle_lst = self.h_params['action_description']['propeller_values'],
                                                power_change_lst = self.h_params['action_description']['power_values'],
                                                epsilon_schedule = self.h_params['action_description']['eps_schedule'])

        else:
            raise ValueError('Action type and designation combo not supported')

        # get the size of the
        action_size = ao.get_action_size()
        selection_size = ao.get_selection_size()
        reset_to_max_power = ao.reset_to_max_power()

        # add columns to the history header for the simulation

        # add columns for raw actions
        for i in range(selection_size):
            self.header.append('org_a'+str(i))
        for i in range(selection_size):
            self.header.append('explore_a' + str(i))

        # add row for path control points
        if type(ao) == ActionOperation.PathActionOperation:
            for i in range(ao.num_control_point):
                self.header.append('cp_x' + str(i))
                self.header.append('cp_y' + str(i))
        else:
            self.header.append("path")

        # add column for critic values
        if n_critic_outputs is None:
            # correction for DQN
            n_critic_outputs = action_size

        for i in range(n_critic_outputs):
            self.header.append('critic_value_'+str(i))

        return action_size, ao, reset_to_max_power

    def get_state_size(self):
        """
        for a specified mover, the observation space size/enumeration is calculated

        :return:
        """

        n_obs = 0

        #movers = self.h_params['movers']
        for name, mover in self.mover_dict.items():

            # only learning movers observe state information currently
            if mover.can_learn:

                n_observations = len(mover.observation_df)

                # also get the measurements generated by the sensors
                for sensor in mover.sensors:
                    #sensor.calc_measurements(self.mover_dict)
                    n_observations += sensor.n_measurements

                    #mover.observation_df = pd.concat([mover.observation_df, sensor.measurement_norm_df], ignore_index=True)

                n_obs = n_observations

        return n_obs

    def get_learning_algorithm(self, action_size, state_size, optimizer_settings):
        """
        Gets the learning algorithm that will drive how the agent is trained. Example: DQN, DDPG, etc.

        :param action_size: integer for the number of actions the agent will have to output from its neural network
        :param state_size: interger for the observation space that the agent will accept into its neural network
        :param optimizer_settings: the data from the input file that outlines how to build the optimizer
        :return: the built learning algorithm object. Serves as the agent as well.
        """

        settings = self.h_params['learning_algorithm']


        last_activation = settings['last_activation']

        loss = settings['loss']
        n_batches = settings['n_batches']
        batch_size = settings['batch_size']
        device = 'cuda'

        if settings['name'] == 'DQN':
            activation = settings['activation']
            layer_numbers = settings['layers']
            layer_numbers = layer_numbers.split(',')
            layer_numbers = [float(i) for i in layer_numbers]
            la = LearningAlgorithms.DQN(action_size, activation, self.h_params, last_activation, layer_numbers, loss, state_size,n_batches, batch_size, device, optimizer_settings)
        elif settings['name'] == 'DDPG':
            max_action_val = np.deg2rad(np.abs(np.float(self.h_params['action_description']['angle_range'].split(',')[0])))
            activation = settings['actor_activation']
            actor_layer_numbers = settings['actor_layers']
            actor_layer_numbers = actor_layer_numbers.split(',')
            actor_layer_numbers = [float(i) for i in actor_layer_numbers]

            critic_layer_numbers = settings['actor_layers']
            critic_layer_numbers = critic_layer_numbers.split(',')
            critic_layer_numbers = [float(i) for i in critic_layer_numbers]

            la = LearningAlgorithms.DDPG(action_size, activation, self.h_params, last_activation, actor_layer_numbers, critic_layer_numbers, loss, state_size, settings['tau'], n_batches, batch_size, device, optimizer_settings, max_action_val)
        else:
            raise ValueError('Learning algorithm currently not supported')

        return la

    def get_memory_mechanism(self):
        """
        parses the input file to create the replay buffer that is described in hte input file.
        The replay buffer stores data for the learning agent to use to learn the solution.

        :return:
        """

        memory_info = self.h_params['replay_data']

        self.replay_storage = ReplayMemory.ReplayStorage(capacity=memory_info['capacity'], extra_fields=[], strategy=memory_info['replay_strategy'], h_params=memory_info)

    def get_evaluation_information(self):
        """
        looks at the information in the input file used for the evaluation episodes. This prepares some of the information
        to use in the evaluation episodes
        :return:
        """

        # get the destination location information
        eval_info = self.h_params['evaluation_init']

        eval_set_size = []
        evaluation_info = pd.DataFrame()
        for key, value in eval_info.items():
            if type(value) == str:
                value_lst = value.split(',')
                eval_set_size.append(len(value_lst))
                evaluation_info[key] = [float(i) for i in value_lst]
            else:
                for sub_key, sub_value in value.items():
                    value_lst = sub_value.split(',')
                    eval_set_size.append(len(value_lst))
                    evaluation_info[key+"-"+sub_key] = [float(i) for i in value_lst]

        if len(set(evaluation_info)) == 1:
            raise ValueError('Evaluation init information are not of consistent lengths. Please verify each variable has the same number of values')

        self.evaluation_info = evaluation_info
        self.n_evaluations = len(evaluation_info)

        # create the files for saveing evaluation information
        file_name = 'Output//' + str(self.h_params['scenario']['experiment_set']) + '//' + str(
            self.h_params['scenario']['trial_num']) + '//Progress//Data//evaluation.csv'
        with open(file_name, 'w') as f:
            f.write("EpNum,SetNum,isSuccess,isCrashed,minDst,cumReward,simTime\n")

        file_name = 'Output//' + str(self.h_params['scenario']['experiment_set']) + '//' + str(
            self.h_params['scenario']['trial_num']) + '//Progress//Data//evaluation_average.csv'
        with open(file_name, 'w') as f:
            f.write("EpNum,successRate,crashRate,avgMinDst,avgCumReward,simTime\n")

    def run_evaluation_set(self, ep_num, reset_to_max_power):
        """
        runs a set of evaluation simulations. The simulations are a deterministic set with a fixed group of initial
        conditions. These are used for a fixed measuring stick for performance of the agent's learning. The initial
        conditions are outlined in the input file.
        :return:
        """

        crash_set = []
        success_set = []
        min_dst_set = []
        cum_reward_set = []
        time_to_completion_set = []
        for i in range(self.n_evaluations):

            # run the simulation in evaluation mode
            cumulative_reward, is_crashed, is_success, min_dst, total_episode_time = self.run_simulation(ep_num,is_evaluation=True,reset_to_max_power=reset_to_max_power,evaluation_number=i)

            print("Evaluation Episode Number={}\tSet Number={}\tSuccess={}\tCrash={}\tProximity={:.3f}\tReward={:.3f}".format(ep_num,i,is_success,is_crashed,min_dst,cumulative_reward))

            # save set numbers information
            crash_set.append(int(is_crashed))
            success_set.append(int(is_success))
            min_dst_set.append(min_dst)
            cum_reward_set.append(cumulative_reward)
            time_to_completion_set.append(total_episode_time)

            # write episode history out to a file
            self.write_history(ep_num, is_evaluation=True, eval_num=i)

            file_name = 'Output//' + str(self.h_params['scenario']['experiment_set']) + '//' + str(
                self.h_params['scenario']['trial_num']) + '//Progress//Data//evaluation.csv'
            with open(file_name,'a') as f:
                f.write(str(ep_num))
                f.write(",")
                f.write(str(i))
                f.write(",")
                f.write(str(is_success))
                f.write(",")
                f.write(str(is_crashed))
                f.write(",")
                f.write(str(min_dst))
                f.write(",")
                f.write(str(cumulative_reward))
                f.write(",")
                f.write(str(total_episode_time))
                f.write("\n")

                f.flush()

        # open average metrics and write the information
        file_name = 'Output//' + str(self.h_params['scenario']['experiment_set']) + '//' + str(
            self.h_params['scenario']['trial_num']) + '//Progress//Data//evaluation_average.csv'
        with open(file_name, 'a') as f:
            str_to_write = ''
            str_to_write += str(ep_num)
            str_to_write += ","
            str_to_write += str(np.mean(success_set))
            str_to_write += ","
            str_to_write += str(np.mean(crash_set))
            str_to_write += ","
            str_to_write += str(np.mean(min_dst_set))
            str_to_write += ","
            str_to_write += str(np.mean(cum_reward_set))
            str_to_write += ","
            str_to_write += str(np.mean(time_to_completion_set))

            str_to_write += "\n"

            f.write(str_to_write)

    def save_hparams(self):
        """
        saves a copy of the hyperparameters used in the simulation for documentation and reference later. The parameters
        are saved in an unchanged state to the trial directory.
        :return:
        """
        with open("Output/"+str(self.h_params['scenario']['experiment_set'])+"/"+str(self.h_params['scenario']['trial_num'])+'/hyper_parameters.yaml', 'w') as file:
            yaml.safe_dump(self.h_params,file)

    def set_data_storage(self):

        self.save_training_data = self.h_params['scenario']['save_training_telemetry']
        self.save_freq = self.h_params['scenario']['save_freq']

    @staticmethod
    def create_environment(file_name):
        """
        Given a yaml file that has configuration details for the environment and hyperparameters for the agents,
        a dictionary is built and returned to the user

        :param file_name: a file name that has all of the hyperparameters. This should be a yaml file
        :return:
        """
        with open(file_name, "r") as stream:
            try:
                hp_data = yaml.safe_load(stream)
            except yaml.YAMLError as exc:
                print(exc)

        # create environment based on the hyper_parameters
        env = Environment(hp_data)

        return env