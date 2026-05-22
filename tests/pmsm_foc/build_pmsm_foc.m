%% build_pmsm_foc.m
% Builds PMSM_FOC_Proxy_Test.slx programmatically.
% Demonstrates: whos output (R03), struct display (R10), build output (R07)
%
% Motor: Interior PMSM, analytical params, 4-pole-pair
% Control: Discrete PI current loops (Ts = 100 µs)
% Inverter: Averaged voltage source (continuous)
% Purpose: Generate real MATLAB MCP output for proxy v2 validation

%% Motor parameters (base workspace)
params.Rs     = 0.0182;      % Stator resistance [Ohm]
params.Ld     = 2.1e-4;      % d-axis inductance [H]
params.Lq     = 4.3e-4;      % q-axis inductance [H]
params.lambda  = 0.1012;     % PM flux linkage [Wb]
params.p      = 4;           % Pole pairs
params.J      = 0.001;       % Rotor inertia [kg·m²]
params.B      = 0.001;       % Viscous damping [N·m·s/rad]
params.Vbus   = 400;         % DC bus voltage [V]
params.Ts     = 1e-4;        % Control sample time [s]
params.Kp_d   = 12.4;        % d-axis PI Kp
params.Ki_d   = 1240;        % d-axis PI Ki
params.Kp_q   = 12.4;        % q-axis PI Kp
params.Ki_q   = 1240;        % q-axis PI Ki
params.omega_ref = 500;      % Reference speed [rad/s]
params.T_max  = 107.63;      % Max torque [Nm]

% Show params — demonstrates struct display compression
params

% Show workspace — demonstrates whos compression
whos

MODEL = 'PMSM_FOC_Proxy_Test';
fprintf('\nBuilding model: %s\n', MODEL);

%% Create model
if bdIsLoaded(MODEL), close_system(MODEL, 0); end
new_system(MODEL);
open_system(MODEL);

%% Solver settings
set_param(MODEL, ...
    'SolverType', 'Variable-step', ...
    'Solver',     'ode15s', ...
    'RelTol',     '1e-4', ...
    'AbsTol',     '1e-6', ...
    'StopTime',   '0.5', ...
    'MaxStep',    '1e-4');

%% Simscape solver configuration block
add_block('nesl_utility/Solver Configuration', [MODEL '/SolverConfig']);
set_param([MODEL '/SolverConfig'], 'Position', [30 30 130 70]);

%% Electrical reference
add_block('nesl_utility/Electrical Reference', [MODEL '/ElecRef']);
set_param([MODEL '/ElecRef'], 'Position', [30 100 80 140]);

%% Mechanical rotational reference
add_block('nesl_utility/Mechanical Rotational Reference', [MODEL '/MechRef']);
set_param([MODEL '/MechRef'], 'Position', [30 170 80 210]);

%% PMSM block
add_block('ee_lib/Machines/Permanent Magnet Synchronous Machine', [MODEL '/PMSM']);
set_param([MODEL '/PMSM'], ...
    'Position',              [250 80 420 280], ...
    'Stator_resistance',     'params.Rs', ...
    'd_axis_inductance',     'params.Ld', ...
    'q_axis_inductance',     'params.Lq', ...
    'PM_flux_linkage',       'params.lambda', ...
    'Number_of_pole_pairs',  'params.p', ...
    'Rotor_inertia',         'params.J', ...
    'Rotor_damping',         'params.B');

%% Controlled voltage sources (d/q averaged inverter)
add_block('ee_lib/Sources/Controlled Voltage Source', [MODEL '/Vd_src']);
set_param([MODEL '/Vd_src'], 'Position', [130 80 200 140]);

add_block('ee_lib/Sources/Controlled Voltage Source', [MODEL '/Vq_src']);
set_param([MODEL '/Vq_src'], 'Position', [130 180 200 240]);

%% Load torque (constant)
add_block('fl_lib/Mechanical/Rotational Sources/Ideal Torque Source', ...
    [MODEL '/TLoad']);
set_param([MODEL '/TLoad'], 'Position', [460 140 560 220]);

%% Constant load torque signal
add_block('simulink/Sources/Constant', [MODEL '/TLoad_val']);
set_param([MODEL '/TLoad_val'], ...
    'Position', [380 160 440 200], ...
    'Value',    '-params.T_max * 0.5');

%% S-PS converter for load torque
add_block('nesl_utility/Simulink-PS Converter', [MODEL '/S2PS_TLoad']);
set_param([MODEL '/S2PS_TLoad'], 'Position', [460 160 520 200]);

%% Sensing: torque and speed
add_block('nesl_utility/PS-Simulink Converter', [MODEL '/PS2S_T']);
set_param([MODEL '/PS2S_T'], 'Position', [580 140 640 180]);

add_block('nesl_utility/PS-Simulink Converter', [MODEL '/PS2S_w']);
set_param([MODEL '/PS2S_w'], 'Position', [580 200 640 240]);

%% PI controllers (discrete)
add_block('simulink/Discrete/Discrete PID Controller', [MODEL '/PI_d']);
set_param([MODEL '/PI_d'], ...
    'Position',   [30 300 150 360], ...
    'Controller', 'PI', ...
    'SampleTime', 'params.Ts', ...
    'P',          'params.Kp_d', ...
    'I',          'params.Ki_d');

add_block('simulink/Discrete/Discrete PID Controller', [MODEL '/PI_q']);
set_param([MODEL '/PI_q'], ...
    'Position',   [30 400 150 460], ...
    'Controller', 'PI', ...
    'SampleTime', 'params.Ts', ...
    'P',          'params.Kp_q', ...
    'I',          'params.Ki_q');

%% Reference currents
add_block('simulink/Sources/Constant', [MODEL '/id_ref']);
set_param([MODEL '/id_ref'], 'Position', [30 250 110 290], 'Value', '0');

add_block('simulink/Sources/Constant', [MODEL '/iq_ref']);
set_param([MODEL '/iq_ref'], ...
    'Position', [30 480 110 520], ...
    'Value',    'params.T_max / (1.5 * params.p * params.lambda)');

%% S-PS converters for Vd/Vq
add_block('nesl_utility/Simulink-PS Converter', [MODEL '/S2PS_Vd']);
set_param([MODEL '/S2PS_Vd'], 'Position', [170 300 230 340]);

add_block('nesl_utility/Simulink-PS Converter', [MODEL '/S2PS_Vq']);
set_param([MODEL '/S2PS_Vq'], 'Position', [170 400 230 440]);

%% Output logging
add_block('simulink/Sinks/To Workspace', [MODEL '/log_torque']);
set_param([MODEL '/log_torque'], ...
    'Position',     [680 140 780 180], ...
    'VariableName', 'torque_out', ...
    'SampleTime',   'params.Ts', ...
    'SaveFormat',   'Array');

add_block('simulink/Sinks/To Workspace', [MODEL '/log_speed']);
set_param([MODEL '/log_speed'], ...
    'Position',     [680 200 780 240], ...
    'VariableName', 'speed_out', ...
    'SampleTime',   'params.Ts', ...
    'SaveFormat',   'Array');

%% Save
save_system(MODEL);
fprintf('Model saved: %s.slx\n', MODEL);
fprintf('Blocks: %d\n', length(find_system(MODEL, 'SearchDepth', 1, 'Type', 'Block')));
fprintf('Run run_pmsm_foc_sim.m to simulate.\n');
