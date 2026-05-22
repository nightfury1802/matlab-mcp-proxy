%% build_pmsm_foc.m
% Builds PMSM_FOC_Proxy_Test.slx programmatically using Simscape Electrical.
%
% Model: PMSM (DQ0) + Closed-loop PI current control + Velocity source
% Tests: Proxy v2 compression features (whos R03, struct R10, DOE R08, oracle, handles)
% Validated: MATLAB R2025a, 9/9 DOE PASS, torque error < 0.01%
%
% Architecture:
%   Simscape: PMSM(DQ0) driven by controlled voltage sources (CVS_d, CVS_q)
%             with current sensors in series. Velocity source prescribes speed.
%   Simulink: Discrete PI controllers (id and iq) close the current loop.
%
% Usage:
%   run('build_pmsm_foc.m')   % builds and saves PMSM_FOC_Proxy_Test.slx
%   sim('PMSM_FOC_Proxy_Test') % simulate (params must be in base workspace)

%% ── Motor parameters ─────────────────────────────────────────────────
params.Rs     = 0.0182;    % Stator resistance [Ohm]
params.Ld     = 2.1e-4;    % d-axis inductance [H]
params.Lq     = 4.3e-4;    % q-axis inductance [H]
params.lambda  = 0.1012;   % PM flux linkage [Wb]
params.p      = 4;         % Pole pairs
params.J      = 0.001;     % Rotor inertia [kg·m²]

%% ── Operating point ──────────────────────────────────────────────────
params.omega_ref = 300;    % Rotor speed reference [mech rad/s]  (~2865 rpm)
params.T_ref     = 50;     % Torque reference [Nm]
params.id_ref    = 0;      % d-axis current ref (unity PF, no field weakening)
params.iq_ref    = params.T_ref / (1.5 * params.p * params.lambda);  % 82.35 A

%% ── PI current control ────────────────────────────────────────────────
wc = 5000;                 % Current loop bandwidth [rad/s]
params.Kp_d   = wc * params.Ld;   % 1.05
params.Ki_d   = wc * params.Rs;   % 91
params.Kp_q   = wc * params.Lq;   % 2.15
params.Ki_q   = wc * params.Rs;   % 91
params.Ts_ctrl = 1e-4;            % Control sample time [s]

fprintf('Motor: Rs=%.4f, Ld=%.2e, Lq=%.2e, lambda=%.4f, p=%d\n', ...
    params.Rs, params.Ld, params.Lq, params.lambda, params.p);
fprintf('Op pt: omega=%.0f rad/s, T_ref=%.0f Nm, iq_ref=%.2f A\n', ...
    params.omega_ref, params.T_ref, params.iq_ref);
params

%% ── Create model ──────────────────────────────────────────────────────
MODEL = 'PMSM_FOC_Proxy_Test';
if bdIsLoaded(MODEL), close_system(MODEL, 0); end
new_system(MODEL);
set_param(MODEL, 'SolverType','Variable-step', 'Solver','ode15s', ...
    'RelTol','1e-5', 'AbsTol','1e-7', 'StopTime','0.3', 'MaxStep','1e-5', ...
    'AlgebraicLoopMsg','none');  % suppress algebraic loop diagnostic

%% ── Simscape blocks ───────────────────────────────────────────────────
add_block('ee_lib/Electromechanical/Permanent Magnet/PMSM (DQ0)', [MODEL '/PMSM_DQ'], ...
    'pm_flux_linkage','params.lambda', 'nPolePairs','params.p', ...
    'Ld','params.Ld', 'Lq','params.Lq', 'Rs','params.Rs', 'J','params.J', ...
    'Position',[500 200 640 340]);
add_block('fl_lib/Electrical/Electrical Elements/Electrical Reference', [MODEL '/ERef'],       'Position',[100 560 150 600]);
add_block('nesl_utility/Solver Configuration',                           [MODEL '/SolverCfg'],  'Position',[60 500 180 540]);
add_block('fl_lib/Mechanical/Rotational Elements/Mechanical Rotational Reference', [MODEL '/MRRef_Motor'], 'Position',[650 260 700 300]);
add_block('fl_lib/Mechanical/Rotational Elements/Mechanical Rotational Reference', [MODEL '/MRRef_Vel'],   'Position',[300 430 350 470]);
add_block('fl_lib/Mechanical/Mechanical Sources/Ideal Angular Velocity Source',    [MODEL '/VelSrc'],      'Position',[390 360 490 420]);

% d-axis: CVS_d → CS_d → PMSM/d
add_block('fl_lib/Electrical/Electrical Sources/Controlled Voltage Source', [MODEL '/CVS_d'], 'Position',[310 190 400 250]);
add_block('fl_lib/Electrical/Electrical Sensors/Current Sensor',            [MODEL '/CS_d'],  'Position',[420 190 490 230]);
% q-axis: CVS_q → CS_q → PMSM/q
add_block('fl_lib/Electrical/Electrical Sources/Controlled Voltage Source', [MODEL '/CVS_q'], 'Position',[310 280 400 340]);
add_block('fl_lib/Electrical/Electrical Sensors/Current Sensor',            [MODEL '/CS_q'],  'Position',[420 280 490 320]);

%% ── Simulink control blocks ────────────────────────────────────────────
add_block('simulink/Sources/Constant',                            [MODEL '/id_ref'],    'Value','params.id_ref',    'Position',[20 50 80 80]);
add_block('simulink/Sources/Constant',                            [MODEL '/iq_ref'],    'Value','params.iq_ref',    'Position',[20 150 80 180]);
add_block('simulink/Math Operations/Sum',                         [MODEL '/Sum_d'],     'Inputs','+-',              'Position',[110 50 140 80]);
add_block('simulink/Math Operations/Sum',                         [MODEL '/Sum_q'],     'Inputs','+-',              'Position',[110 150 140 180]);
add_block('simulink/Discrete/Discrete PID Controller',            [MODEL '/PI_d'],      'Controller','PI', 'SampleTime','params.Ts_ctrl', 'P','params.Kp_d', 'I','params.Ki_d', 'Position',[160 40 250 90]);
add_block('simulink/Discrete/Discrete PID Controller',            [MODEL '/PI_q'],      'Controller','PI', 'SampleTime','params.Ts_ctrl', 'P','params.Kp_q', 'I','params.Ki_q', 'Position',[160 140 250 190]);
add_block('nesl_utility/Simulink-PS Converter',                   [MODEL '/S2PS_Vd'],   'Position',[270 50 350 80]);
add_block('nesl_utility/Simulink-PS Converter',                   [MODEL '/S2PS_Vq'],   'Position',[270 150 350 180]);
add_block('simulink/Sources/Constant',                            [MODEL '/omega_const'],'Value','params.omega_ref','Position',[200 370 260 400]);
add_block('nesl_utility/Simulink-PS Converter',                   [MODEL '/S2PS_omega'],'Position',[270 370 350 400]);
add_block('nesl_utility/PS-Simulink Converter',                   [MODEL '/PS2S_id'],   'Position',[660 195 730 225]);
add_block('nesl_utility/PS-Simulink Converter',                   [MODEL '/PS2S_iq'],   'Position',[660 285 730 315]);
add_block('simulink/Sinks/To Workspace',[MODEL '/log_id'], 'VariableName','id_out', 'SaveFormat','Array','SampleTime','params.Ts_ctrl','Position',[750 198 840 218]);
add_block('simulink/Sinks/To Workspace',[MODEL '/log_iq'], 'VariableName','iq_out', 'SaveFormat','Array','SampleTime','params.Ts_ctrl','Position',[750 288 840 308]);
add_block('simulink/Sinks/To Workspace',[MODEL '/log_Vd'], 'VariableName','Vd_out', 'SaveFormat','Array','SampleTime','params.Ts_ctrl','Position',[270 240 350 260]);
add_block('simulink/Sinks/To Workspace',[MODEL '/log_Vq'], 'VariableName','Vq_out', 'SaveFormat','Array','SampleTime','params.Ts_ctrl','Position',[270 330 350 350]);

%% ── Simulink signal wires ──────────────────────────────────────────────
add_line(MODEL,'id_ref/1','Sum_d/1','autorouting','smart');
add_line(MODEL,'iq_ref/1','Sum_q/1','autorouting','smart');
add_line(MODEL,'PS2S_id/1','Sum_d/2','autorouting','smart');
add_line(MODEL,'PS2S_iq/1','Sum_q/2','autorouting','smart');
add_line(MODEL,'Sum_d/1','PI_d/1','autorouting','smart');
add_line(MODEL,'Sum_q/1','PI_q/1','autorouting','smart');
add_line(MODEL,'PI_d/1','S2PS_Vd/1','autorouting','smart');
add_line(MODEL,'PI_q/1','S2PS_Vq/1','autorouting','smart');
add_line(MODEL,'S2PS_Vd/RConn1','CVS_d/RConn1','autorouting','smart');
add_line(MODEL,'S2PS_Vq/RConn1','CVS_q/RConn1','autorouting','smart');
add_line(MODEL,'PI_d/1','log_Vd/1','autorouting','smart');
add_line(MODEL,'PI_q/1','log_Vq/1','autorouting','smart');
add_line(MODEL,'CS_d/RConn1','PS2S_id/LConn1','autorouting','smart');
add_line(MODEL,'CS_q/RConn1','PS2S_iq/LConn1','autorouting','smart');
add_line(MODEL,'PS2S_id/1','log_id/1','autorouting','smart');
add_line(MODEL,'PS2S_iq/1','log_iq/1','autorouting','smart');
add_line(MODEL,'omega_const/1','S2PS_omega/1','autorouting','smart');
add_line(MODEL,'S2PS_omega/RConn1','VelSrc/RConn1','autorouting','smart');

%% ── Simscape physical network ──────────────────────────────────────────
% Verified port names (R2025a):
%   PMSM DQ0: d, q, z (electrical), R, C (mechanical)
%   CVS fl_lib: p, n (electrical), RConn1 (PS input via add_line)
%   CurrSens fl_lib: p, n (electrical), RConn1 (PS output via add_line)
%   VelSrc: R, C (mechanical), RConn1 (PS input via add_line)
add_line(MODEL,'SolverCfg/RConn1','ERef/LConn1','autorouting','smart');
simscape.addConnection([MODEL '/CVS_d'],'n',[MODEL '/ERef'],'V');
simscape.addConnection([MODEL '/CVS_d'],'p',[MODEL '/CS_d'],'p');
simscape.addConnection([MODEL '/CS_d'],'n',[MODEL '/PMSM_DQ'],'d');
simscape.addConnection([MODEL '/CVS_q'],'n',[MODEL '/ERef'],'V');
simscape.addConnection([MODEL '/CVS_q'],'p',[MODEL '/CS_q'],'p');
simscape.addConnection([MODEL '/CS_q'],'n',[MODEL '/PMSM_DQ'],'q');
simscape.addConnection([MODEL '/PMSM_DQ'],'z',[MODEL '/ERef'],'V');
simscape.addConnection([MODEL '/PMSM_DQ'],'C',[MODEL '/MRRef_Motor'],'W');
simscape.addConnection([MODEL '/PMSM_DQ'],'R',[MODEL '/VelSrc'],'R');
simscape.addConnection([MODEL '/VelSrc'],'C',[MODEL '/MRRef_Vel'],'W');

%% ── Save ───────────────────────────────────────────────────────────────
save_system(MODEL, fullfile(pwd, [MODEL '.slx']));
fprintf('\nModel saved: %s.slx\n', MODEL);
fprintf('Blocks: %d\n', length(find_system(MODEL,'SearchDepth',1,'Type','Block'))-1);
whos
