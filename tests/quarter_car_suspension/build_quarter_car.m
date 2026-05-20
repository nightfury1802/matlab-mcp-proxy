%% build_quarter_car.m
% Quarter-Car Active Suspension — programmatic Simscape build
% Vehicle mass: 400 kg (sprung), wheel: 40 kg (unsprung)
% Suspension: ks=16000 N/m, cs=1400 Ns/m
% Tire stiffness: kt=190000 N/m
% Active actuator: PD controller on chassis velocity

mdl = 'QuarterCarActiveSuspension';

%% --- Parameters -------------------------------------------------------
ms  = 400;      % sprung mass (chassis) [kg]
mu  = 40;       % unsprung mass (wheel) [kg]
ks  = 16000;    % suspension spring     [N/m]
cs  = 1400;     % suspension damper     [Ns/m]
kt  = 190000;   % tyre stiffness        [N/m]
Kp  = 2000;     % PD proportional gain
Kd  = 800;      % PD derivative gain
bump_height = 0.05;  % road bump [m]
bump_time   = 0.5;   % bump onset [s]

%% --- Close / create model --------------------------------------------
if bdIsLoaded(mdl), close_system(mdl, 0); end
new_system(mdl);
open_system(mdl);

set_param(mdl, ...
    'Solver',         'ode23t', ...
    'RelTol',         '1e-4',   ...
    'AbsTol',         '1e-6',   ...
    'StopTime',       '4',      ...
    'SaveTime',       'on',     ...
    'SaveOutput',     'on',     ...
    'OutputSaveName', 'yout');

load_system('fl_lib');
load_system('nesl_utility');
load_system('simulink');

%% --- Block paths ------------------------------------------------------
MASS   = 'fl_lib/Mechanical/Translational Elements/Mass';
SPRING = 'fl_lib/Mechanical/Translational Elements/Translational Spring';
DAMPER = 'fl_lib/Mechanical/Translational Elements/Translational Damper';
FORCE  = 'fl_lib/Mechanical/Mechanical Sources/Ideal Force Source';
VELOC  = 'fl_lib/Mechanical/Mechanical Sources/Ideal Translational Velocity Source';
SENSOR = 'fl_lib/Mechanical/Mechanical Sensors/Ideal Translational Motion Sensor';
TREF   = 'fl_lib/Mechanical/Translational Elements/Mechanical Translational Reference';
SCFG   = 'nesl_utility/Solver Configuration';
PS2SL  = 'nesl_utility/PS-Simulink Converter';
SL2PS  = 'nesl_utility/Simulink-PS Converter';
SCOPE  = 'simulink/Sinks/Scope';
TOWS   = 'simulink/Sinks/To Workspace';
GAIN   = 'simulink/Math Operations/Gain';
SUM    = 'simulink/Math Operations/Sum';
DERIV  = 'simulink/Continuous/Derivative';
STEP   = 'simulink/Sources/Step';

%% --- Helper: add_block with position ----------------------------------
function blk = ab(mdl, lib, name, pos)
    blk = [mdl '/' name];
    add_block(lib, blk, 'Position', pos);
end

%% --- Physical network ------------------------------------------------
% Column 1: Road / Tyre (x=50)
ab(mdl, TREF,   'Ground1',      [50  300 80  330]);
ab(mdl, VELOC,  'RoadVel',      [50  200 110 240]);   % road velocity input
ab(mdl, SPRING, 'TyreSpring',   [50  130 110 170]);   % kt
ab(mdl, MASS,   'WheelMass',    [50   50 110  90]);   % mu

% Column 2: Suspension (x=250)
ab(mdl, SPRING, 'SuspSpring',   [250 200 310 240]);   % ks
ab(mdl, DAMPER, 'SuspDamper',   [250 130 310 170]);   % cs
ab(mdl, FORCE,  'Actuator',     [250  50 310  90]);   % F_act (active)

% Column 3: Chassis (x=450)
ab(mdl, MASS,   'ChassisMass',  [450 200 510 240]);   % ms
ab(mdl, TREF,   'Ground2',      [450 300 480 330]);

% Sensors
ab(mdl, SENSOR, 'SensorChassis',[450  50 510  90]);   % chassis velocity
ab(mdl, SENSOR, 'SensorWheel',  [250 280 310 320]);   % wheel velocity (for ref)

% Solver
ab(mdl, SCFG,   'SolverCfg',    [650 200 750 250]);

%% --- Set physical parameters -----------------------------------------
set_param([mdl '/WheelMass'],   'mass',         num2str(mu));
set_param([mdl '/ChassisMass'], 'mass',         num2str(ms));
set_param([mdl '/TyreSpring'],  'spr_rate',     num2str(kt));
set_param([mdl '/SuspSpring'],  'spr_rate',     num2str(ks));
set_param([mdl '/SuspDamper'],  'D',            num2str(cs));

%% --- Simscape physical connections -----------------------------------
% Ground1 → RoadVel(C)
simscape.addConnection([mdl '/Ground1'],     'V', [mdl '/RoadVel'],     'C');
% RoadVel(R) → TyreSpring(C)  [road surface node]
simscape.addConnection([mdl '/RoadVel'],     'R', [mdl '/TyreSpring'],  'C');
% TyreSpring(R) → WheelMass(M)  [wheel node]
simscape.addConnection([mdl '/TyreSpring'],  'R', [mdl '/WheelMass'],   'M');
% WheelMass(M) → SuspSpring(C), SuspDamper(C), Actuator(C), SensorWheel(C)
simscape.addConnection([mdl '/WheelMass'],   'M', [mdl '/SuspSpring'],  'C');
simscape.addConnection([mdl '/WheelMass'],   'M', [mdl '/SuspDamper'],  'C');
simscape.addConnection([mdl '/WheelMass'],   'M', [mdl '/Actuator'],    'C');
simscape.addConnection([mdl '/WheelMass'],   'M', [mdl '/SensorWheel'], 'C');
% SuspSpring(R), SuspDamper(R), Actuator(R), SensorChassis → ChassisMass(M)
simscape.addConnection([mdl '/SuspSpring'],  'R', [mdl '/ChassisMass'], 'M');
simscape.addConnection([mdl '/SuspDamper'],  'R', [mdl '/ChassisMass'], 'M');
simscape.addConnection([mdl '/Actuator'],    'R', [mdl '/ChassisMass'], 'M');
simscape.addConnection([mdl '/SensorChassis'],'R',[mdl '/ChassisMass'], 'M');
% SensorWheel(R) → SuspSpring(C) side (already connected via WheelMass)
simscape.addConnection([mdl '/SensorWheel'], 'R', [mdl '/SuspSpring'],  'C');
% ChassisMass(M) → SensorChassis(C), Ground2
simscape.addConnection([mdl '/SensorChassis'],'C',[mdl '/Ground2'],     'V');
% Solver connects to Ground2 node via add_line (LConn/RConn API)
add_line(mdl, 'SolverCfg/RConn1', 'Ground2/LConn1', 'autorouting','smart');

%% --- Road velocity input (PS): step bump → ramp velocity pulse -------
% Road displacement = bump_height * ramp up (not a pure step in velocity)
% Model as: velocity source gets a Step signal through SL→PS
ab(mdl, STEP,   'BumpStep',    [50  380 100 420]);
ab(mdl, SL2PS,  'SL2PS_Road',  [150 380 210 420]);
set_param([mdl '/BumpStep'], 'Time', num2str(bump_time), ...
    'Before', '0', 'After', num2str(bump_height));

add_line(mdl, 'BumpStep/1',    'SL2PS_Road/1',    'autorouting','smart');
add_line(mdl, 'SL2PS_Road/1',  'RoadVel/S',       'autorouting','smart');

%% --- Chassis velocity sensor → PS2SL → PD controller ----------------
ab(mdl, PS2SL,  'PS2SL_V',     [600  50 660  90]);
add_line(mdl, 'SensorChassis/V', 'PS2SL_V/1',     'autorouting','smart');

% PD: F = Kp*v + Kd*dv/dt
ab(mdl, GAIN,   'GainKp',      [700  30 760  70]);
ab(mdl, DERIV,  'Deriv',       [700  90 760 130]);
ab(mdl, GAIN,   'GainKd',      [700 150 760 190]);
ab(mdl, SUM,    'PDsum',       [800  70 840 130]);
ab(mdl, SL2PS,  'SL2PS_F',     [870  70 930 130]);
set_param([mdl '/GainKp'],  'Gain', num2str(Kp));
set_param([mdl '/GainKd'],  'Gain', num2str(Kd));
set_param([mdl '/PDsum'],   'Inputs', '++');

add_line(mdl, 'PS2SL_V/1',  'GainKp/1',   'autorouting','smart');
add_line(mdl, 'PS2SL_V/1',  'Deriv/1',    'autorouting','smart');
add_line(mdl, 'Deriv/1',    'GainKd/1',   'autorouting','smart');
add_line(mdl, 'GainKp/1',   'PDsum/1',    'autorouting','smart');
add_line(mdl, 'GainKd/1',   'PDsum/2',    'autorouting','smart');
add_line(mdl, 'PDsum/1',    'SL2PS_F/1',  'autorouting','smart');
add_line(mdl, 'SL2PS_F/1',  'Actuator/S', 'autorouting','smart');

%% --- Scopes & To Workspace -------------------------------------------
ab(mdl, PS2SL, 'PS2SL_Vchk',  [600 160 660 200]);
add_line(mdl, 'SensorChassis/V', 'PS2SL_Vchk/1', 'autorouting','smart');

ab(mdl, TOWS,  'TW_Chassis',  [750 160 830 200]);
set_param([mdl '/TW_Chassis'], 'VariableName','chassis_vel','SaveFormat','Array');
add_line(mdl, 'PS2SL_Vchk/1', 'TW_Chassis/1', 'autorouting','smart');

ab(mdl, SCOPE, 'Scope',       [750 220 830 280]);
add_line(mdl, 'PS2SL_Vchk/1', 'Scope/1', 'autorouting','smart');

%% --- Save ------------------------------------------------------------
save_system(mdl, [pwd '/' mdl '.slx']);
fprintf('\n=== QuarterCarActiveSuspension.slx saved ===\n');
fprintf('  Sprung mass:  %d kg\n', ms);
fprintf('  Unsprung:     %d kg\n', mu);
fprintf('  Suspension:   ks=%d N/m  cs=%d Ns/m\n', ks, cs);
fprintf('  Tyre:         kt=%d N/m\n', kt);
fprintf('  PD gains:     Kp=%d  Kd=%d\n', Kp, Kd);
fprintf('  Road bump:    %.3f m at t=%.1f s\n', bump_height, bump_time);
fprintf('Run: sim(''%s'') to simulate\n', mdl);
