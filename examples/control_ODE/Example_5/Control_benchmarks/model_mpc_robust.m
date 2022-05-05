%% Robust Model Predictive Control for Simple Building Model

% states:
%  x1: T_floor
%  x2: T_facade_internal
%  x3: T_facade_external
%  x4: T_internal
% input:
%  u1: Q_heating_cooling
% disturbances:
%  d1: T_external
%  d2: Q_occupancy
%  d3: Q_solar

load('../TimeSeries/disturb.mat')
disturbances = D;
% load the state space model and weather data
load('ss_model.mat')

% construct discrete SSM
base_Ts = 300; % 300s = 5min
% model continuous
model1 = ss(A,B,C,D);
% model discrete
Ts = 300;
sd = c2d(ss(A, B, C, D), Ts);
Ad = sd.A;
Bd = sd.B(:, 2);
Cd = sd.C(4,:);
Ed = sd.B(:, [1 3 4]);
Dd = 0;
% problem dimensions
nx = size(Ad, 2);
nu = size(Bd, 2);
ny = size(Cd, 1);
nd = size(Ed, 2);

%  worst-case disturbances
d_max = max(diff(disturbances'))';
d_min = min(diff(disturbances'))';
w_mean = 0;
w_var = 0.1;
w_max = 2*((w_mean-w_var)+(2*w_var)*ones(nx,1));
w_min = 2*((w_mean-w_var)+(2*w_var)*zeros(nx,1));

%% MPC formulation via Yalmip
%------------------------------------------------------
% constraints values
umin = 0;
umax = 5000;
ymin = 19;
ymax = 25;
% prediction horizon
N = 1;
% penalty matices from ICML paper
Qu = 1e-6*eye(nu); % input minimization weight
Qu_con = 5e-7*eye(nu); % input minimization weight
Qs = 5e1; % output constraints weight
Qy = 2e1; % output reference tracking weight

% bit of tuning
% Qu = 1e-3*eye(nu); % input minimization weight
% Qs = 5e0; % output constraints weight
% Qy = 1e4; % output reference tracking weight
% variables of the optimization problem
x = sdpvar(nx, N+1, 'full');        % MPC parameter
u = sdpvar(nu, N, 'full');          % decision variables
d = sdpvar(nd, N, 'full');          % disturbances
y_nom = sdpvar(ny, N, 'full');          % internal variable
y_max = sdpvar(ny, N, 'full');          % internal variable
y_min = sdpvar(ny, N, 'full');          % internal variable
sy = sdpvar(ny, N, 'full');          % decision variables - slack for output constraints
su = sdpvar(nu, N, 'full');          % decision variables - slack for input constraints
% yref = sdpvar(ny, 1);               % MPC parameter
yref = sdpvar(ny, N, 'full'); % for time varying reference
con = [];
obj = 0;


for k = 1:N
    % constraints
    con = con + [ x(:, k+1) == Ad*x(:, k) + Bd*u(:, k) + Ed*d(:, k) ];       % state update model
    con = con + [ y_min(:, k) == Cd*(Ad*x(:, k) + Bd*u(:, k) + Ed*(d(:, k) + k*d_min)) ];         % output model min
    con = con + [ y_max(:, k) == Cd*(Ad*x(:, k) + Bd*u(:, k) + Ed*(d(:, k) + k*d_max)) ];         % output model max
    con = con + [ y_nom(:, k) == Cd*(Ad*x(:, k) + Bd*u(:, k) + Ed*(d(:, k))) ];         % output model nominal
%     con = con + [ y_min(:, k) == Cd*(Ad*x(:, k) + Bd*u(:, k) + Ed*(d(:, k)) + k*w_min) ];         % output model min
%     con = con + [ y_max(:, k) == Cd*(Ad*x(:, k) + Bd*u(:, k) + Ed*(d(:, k)) + k*w_max) ];         % output model max

    con = con + [ umin - su(:, k) <= u(:, k) <= umax + su(:, k) ];                    % input constraints
    con = con + [ ymin - sy(:, k) <= y_nom(:, k) <= ymax + sy(:, k) ];    % output constraints
    con = con + [ ymin - sy(:, k) <= y_min(:, k) <= ymax + sy(:, k) ];    % output constraints
    con = con + [ ymin - sy(:, k) <= y_max(:, k) <= ymax + sy(:, k) ];    % output constraints
    % objective function
    obj = obj + sy(:, k)'*Qs*sy(:, k) + (y_nom(:, k)-yref(:, k))'*Qy*(y_nom(:, k)-yref(:, k)) ...
        + u(:, k)'*Qu*u(:, k) + su(:, k)'*Qu_con*su(:, k) ;  
end
options = sdpsettings('verbose', 0,'solver','QUADPROG','QUADPROG.maxit',1e6);

% % MPC optimizer
opt = optimizer(con, obj, options, {x(:, 1), yref, d}, u);
%------------------------------------------------------

%% Simulation Setup
% simulation steps
samples_day = 288; % 288 samples per day with 5 min sampling
start_day = 7;
start_sim = samples_day*start_day;
test_day = 21;
test_sim = samples_day*test_day;
end_day = 28; 
end_sim = samples_day*end_day;
Nsim = end_sim - start_sim;

% initial conditions
x0 = 20*ones(nx,1);
% reference signals
R_day = 20+2*sin([0:2*pi/samples_day:2*pi]);
R_day = R_day(1:end-1);
R_t = repmat(R_day, 1, end_day); %  Sim_days control profile   
% simulation disturbance and reference trajectories
d_prew = disturbances(:,start_sim:end_sim);
r_prew = R_t(:,start_sim:end_sim);

%% Closed Loop Simulation
param_uncertainty = 1;
add_uncertainty = 1;
if add_uncertainty
    w_mean = 0;
    w_var = 0.1;
else
    w_mean = 0;
    w_var = 0.0;
end
if param_uncertainty
    theta_mean = 0;
    theta_var = 0.01;
else
    theta_mean = 0;
    theta_var = 0.00;   
end

Eval_runs  = 20;  % number of randomized closed-loop simulations, Paper value: 20

MAE_constr = zeros(Eval_runs,1);
MSE_ref = zeros(Eval_runs,1);
MA_energy = zeros(Eval_runs,1);
CPU_time_mean = zeros(Eval_runs,1);
CPU_time_max = zeros(Eval_runs,1);

for run = 1:Eval_runs  
    Xsim = x0;
    Usim = [];
    Ysim = [];
    Psim = [];
    Ref = [];
    LB = [];
    UB = [];
    StepTime = zeros(Nsim,1);
    
    % closed-loop simulation
    for k = 1:Nsim        
        if k == Nsim/4 | k == Nsim/2 | k == 0.75*Nsim | k == Nsim
            fprintf('Optimization %d/%d complete on %d%%\n',run, Eval_runs, (k*100)/Nsim);
        end

        % MPC control
        start_t = clock;
        ref = r_prew(k:k+N-1);
        d0 = d_prew(:,k:k+N-1);
        xt = Xsim(:, end);
        [u, problem, info] = opt{{xt, ref, d0}};  
%         if problem~=0
%             error(info{1});
%         end
        uopt = value(u(:, 1));        
        step_time = etime(clock, start_t);                  %  elapsed time of one sim. step
        StepTime(k) = step_time;

    %     uncertainties
        w = (w_mean-w_var)+(2*w_var)*rand(nx,1); % additive uncertainty
        theta = (1+theta_mean-theta_var)+(2*theta_var)*rand(nx,nx);  % parametric uncertainty

    %     clipping
        if uopt> umax
            uopt = umax;
        end
        if uopt< umin
            uopt = umin;
        end    
        Usim = [Usim, uopt];

        % system simulation
        xn = theta.*Ad*xt + Bd*uopt + Ed*d_prew(:,k) + w;
        yn = Cd*xt;

        Xsim = [Xsim, xn];
        Ysim = [Ysim, yn];
        Psim = [Psim, d_prew(:,k)];
        Ref = [Ref, ref(1)];


    % end of closed-loop simulation
    end
    CPU_time_mean(run) = mean(StepTime);
    CPU_time_max(run) = max(StepTime);

    % performance metrics
    Ysim_test = Ysim(test_sim-start_sim:end_sim-start_sim);    
    MAE_constr(run) = sum(Ysim_test(Ysim_test<ymin))/length(Ysim_test) + sum(Ysim_test(Ysim_test>ymax))/length(Ysim_test);
    MSE_ref(run) = mean((Ysim_test-Ref(test_sim-start_sim:end_sim-start_sim)).*(Ysim_test-Ref(test_sim-start_sim:end_sim-start_sim)));
    MA_energy(run) = mean(abs(Usim(test_sim-start_sim:end_sim-start_sim)));

end

MAE_constr_paper = mean(MAE_constr)
MSE_ref_paper = mean(MSE_ref)
MA_energy_paper = mean(MA_energy)
CPU_time_mean_paper = mean(CPU_time_mean)*1000
CPU_time_max_paper = max(CPU_time_max)*1000


%% Plots
close all
t = 0:Nsim-1;
LB = ymin*ones(size(Ysim));
UB = ymax*ones(size(Ysim));

figure
subplot(3,1,1)
plot(t,Ysim,'LineWidth',2)
hold on
plot(t,Ref,'r--','LineWidth',2)
plot(t,LB,'g--','LineWidth',2)
plot(t,UB,'g--','LineWidth',2)
title('Room Temperature')
legend('T room', 'reference','location','bestoutside')
xlabel('time')
ylabel('temperature [\circC]')

subplot(3,1,2)
stairs(t,Usim,'LineWidth',2)
title('Input')
legend('Q heating','location','bestoutside')
xlabel('time')
ylabel('Q')

subplot(3,1,3)
plot(t,Psim,'LineWidth',2)
title('Disturbances')
legend('T external','Q occupancy','Q solar','location','bestoutside')
xlabel('time')
ylabel('')

%------------------------------------------------------
