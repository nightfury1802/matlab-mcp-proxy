% Scenario: auto-display of 1000-row vectors
% Compression rule tested: R04 (compress_large_arrays)
% Expected reduction: ~85%
% Run via: evaluate_matlab_code with this script content
tout   = linspace(0, 1, 1000)';
torque = 107.63 * (1 - exp(-tout/0.1));
tout
torque
fprintf('Final torque: %.4f Nm\n', torque(end));
