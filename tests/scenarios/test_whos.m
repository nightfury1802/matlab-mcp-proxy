% Scenario: workspace variable listing (whos)
% Compression rule tested: R03 (compress_whos)
% Expected reduction: ~74%
% Run via: evaluate_matlab_code with this script content
omega_r = 0;
tout    = zeros(1000,1);
torque  = zeros(1000,1);
params  = struct('Ld',2.1e-4,'Lq',4.3e-4,'Rs',0.0182,'lambda',0.1012, ...
                 'p',4,'Vbus',400,'omega_b',1047.2,'I_max',300);
LUT_id  = zeros(51,51,5);
LUT_iq  = zeros(51,51,5);
whos
