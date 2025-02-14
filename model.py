import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import os, copy
import numpy as np

class Linear_DQN(nn.Module):
    def __init__(self, input_size, hidden_size, output_size):
        super().__init__()
        self.linear1 = nn.Linear(input_size, hidden_size)
        self.linear2 = nn.Linear(hidden_size, output_size)
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    def forward(self, x):
        x = F.relu(self.linear1(x))
        x = self.linear2(x)
        return x

    def save(self, file_name='linear_model.pth'):
        model_folder_path = './model'
        if not os.path.exists(model_folder_path):
            os.makedirs(model_folder_path)

        file_name = os.path.join(model_folder_path, file_name)
        torch.save(self.state_dict(), file_name)


class Trainer:
    def __init__(self, model, lr, gamma):
        self.lr = lr
        self.gamma = gamma
        self.model = model
        self.optimizer = optim.Adam(model.parameters(), lr=self.lr)
        self.criterion = nn.MSELoss()
        self.losses = []

    def train_step(self, state, action, reward, next_state, done):
        state = torch.tensor(np.array(state), dtype=torch.float).to(self.model.device)
        next_state = torch.tensor(np.array(next_state), dtype=torch.float).to(self.model.device)
        action = torch.tensor(np.array(action), dtype=torch.long).to(self.model.device)
        reward = torch.tensor(np.array(reward), dtype=torch.float).to(self.model.device)
        # (n, x)
        if len(state.shape) == 1:
            # (1, x)
            state = torch.unsqueeze(state, 0)
            next_state = torch.unsqueeze(next_state, 0)
            action = torch.unsqueeze(action, 0)
            reward = torch.unsqueeze(reward, 0)
            done = (done, )

        # 1: predicted Q values with current state
        pred = self.model(state)

        target = pred.clone()
        for idx in range(len(done)):
            Q_new = reward[idx]
            if not done[idx]:
                Q_new = reward[idx] + self.gamma * torch.max(self.model(next_state[idx]))

            target[idx][torch.argmax(action[idx]).item()] = Q_new
    
        # 2: Q_new = r + y * max(next_predicted Q value) -> only do this if not done
        # pred.clone()
        # preds[argmax(action)] = Q_new
        self.optimizer.zero_grad()
        loss = self.criterion(target, pred)
        loss.backward()
        self.losses.append(loss.item())

        self.optimizer.step()

class DoubleDQNTrainer:
    def __init__(self, model, lr, gamma):
        self.lr = lr
        self.gamma = gamma
        self.model = model
        self.target_model = copy.deepcopy(model)
        self.optimizer = optim.Adam(self.model.parameters(), lr=self.lr)
        self.criterion = nn.MSELoss()
        self.update_steps = 0
        self.update_target_every = 1000  # Update target network every 1000 steps
        self.losses = []

    def train_step(self, state, action, reward, next_state, done):
        state = torch.tensor(np.array(state), dtype=torch.float).to(self.model.device)
        next_state = torch.tensor(np.array(next_state), dtype=torch.float).to(self.model.device)
        action = torch.tensor(np.array(action), dtype=torch.long).to(self.model.device)
        reward = torch.tensor(np.array(reward), dtype=torch.float).to(self.model.device)

        if len(state.shape) == 1:
            state = torch.unsqueeze(state, 0)
            next_state = torch.unsqueeze(next_state, 0)
            action = torch.unsqueeze(action, 0)
            reward = torch.unsqueeze(reward, 0)
            done = (done, )

        pred = self.model(state)
        target = pred.clone()
        with torch.no_grad():
            next_pred = self.target_model(next_state)
        for idx in range(len(done)):
            Q_new = reward[idx]
            if not done[idx]:
                Q_new = reward[idx] + self.gamma * torch.max(next_pred[idx])
            target[idx][torch.argmax(action[idx]).item()] = Q_new

        self.optimizer.zero_grad()
        loss = self.criterion(target, pred)
        loss.backward()
        self.optimizer.step()
        self.losses.append(loss.item())

        self.update_steps += 1
        if self.update_steps % self.update_target_every == 0:
            self.target_model.load_state_dict(self.model.state_dict())

class PPOModel(nn.Module):
    def __init__(self, input_size, hidden_size, output_size):
        super(PPOModel, self).__init__()
        self.fc1 = nn.Linear(input_size, hidden_size)
        self.policy_head = nn.Linear(hidden_size, output_size)
        self.value_head = nn.Linear(hidden_size, 1)
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    def forward(self, x):
        x = F.relu(self.fc1(x))
        logits = self.policy_head(x)
        value = self.value_head(x)
        return logits, value.squeeze(-1)

    def save(self, file_name='ppo_model.pth'):
        model_folder_path = './model'
        if not os.path.exists(model_folder_path):
            os.makedirs(model_folder_path)
        file_name = os.path.join(model_folder_path, file_name)
        torch.save(self.state_dict(), file_name)

class PPOTrainer:
    def __init__(self, model, lr, gamma, clip_epsilon=0.2, value_loss_coeff=0.5, entropy_coeff=0.01):
        self.model = model
        self.gamma = gamma
        self.clip_epsilon = clip_epsilon
        self.value_loss_coeff = value_loss_coeff
        self.entropy_coeff = entropy_coeff
        self.optimizer = optim.Adam(model.parameters(), lr=lr)
        self.losses = []

    def train_step(self, states, actions, old_log_probs, returns, advantages):
        logits, values = self.model(states)
        dist = torch.distributions.Categorical(logits=logits)
        entropy = dist.entropy().mean()
        new_log_probs = dist.log_prob(actions)

        ratio = torch.exp(new_log_probs - old_log_probs)
        surr1 = ratio * advantages
        surr2 = torch.clamp(ratio, 1 - self.clip_epsilon, 1 + self.clip_epsilon) * advantages
        policy_loss = -torch.min(surr1, surr2).mean()

        value_loss = F.mse_loss(values, returns)
        loss = policy_loss + self.value_loss_coeff * value_loss - self.entropy_coeff * entropy

        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        self.losses.append(loss.item())
