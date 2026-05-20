% Scenario: real Simscape simulation error (requires test_PMSM_FEM_foc model)
% Compression rules tested: R05 (block paths), R11 (boilerplate), R12 (caused-by)
% Expected reduction: ~50%
% Prerequisite: test_PMSM_FEM_foc.slx must exist in the working folder
% Run via: run_matlab_file pointing to this file
try
    out = sim('test_PMSM_FEM_foc', 'StopTime', '0.001');
    fprintf('Simulation OK: final torque = %.2f Nm\n', out.torque(end));
catch ME
    fprintf('ERROR: %s\n', ME.message);
    for i = 1:length(ME.stack)
        fprintf('  In %s (line %d)\n', ME.stack(i).name, ME.stack(i).line);
    end
    if ~isempty(ME.cause)
        fprintf('Caused by: %s\n', ME.cause{1}.message);
    end
end
