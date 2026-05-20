% Scenario: Simulink model reference rebuild output
% Compression rule tested: R07 (compress_build_output)
% Expected reduction: ~56%
% Prerequisite: test_PMSM_FEM_foc.slx must exist in the working folder
% Run via: run_matlab_file pointing to this file
% Force rebuild by touching the model
fprintf('Triggering model reference build for test_PMSM_FEM_foc...\n');
slbuild('test_PMSM_FEM_foc');
fprintf('Build complete.\n');
