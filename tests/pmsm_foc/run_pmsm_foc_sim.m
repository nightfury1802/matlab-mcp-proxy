%% run_pmsm_foc_sim.m
% Phase 1: Normal simulation → Context Handle (SIM_RESULT → SimHandle#N)
% Phase 2: Bad params → Derivative error → Oracle hint
% Phase 3: Repeated RCOND warnings → dedup + oracle hint
%
% Run AFTER build_pmsm_foc.m

MODEL = 'PMSM_FOC_Proxy_Test';
if ~bdIsLoaded(MODEL)
    fprintf('Loading model...\n');
    load_system(MODEL);
end

%% === PHASE 1: Normal simulation ===
fprintf('\n=== PHASE 1: Normal simulation ===\n');
fprintf('Expected proxy output: SimHandle#N summary (not full dump)\n\n');
try
    out = sim(MODEL, 'StopTime', '0.3');
    % Print results — this block generates SIM_RESULT output for proxy
    fprintf('Simulation complete.\n');
    T_final = out.torque_out(end);
    w_final = out.speed_out(end);
    fprintf('\ntorque =\n\n   %.4f\n\n', T_final);
    fprintf('speed =\n\n   %.4f\n\n', w_final);
    fprintf('Final torque: %.2f Nm\n', T_final);
    fprintf('Final speed: %.2f rad/s\n', w_final);
    fprintf('Peak torque: %.2f Nm\n', max(out.torque_out));
catch ME
    fprintf('Phase 1 error: %s\n', ME.message);
end

%% === PHASE 2: Derivative error (Rs = 0) ===
fprintf('\n=== PHASE 2: Derivative error (Rs = 0) ===\n');
fprintf('Expected proxy output: [ORACLE hint] + compressed error\n\n');
params_backup = params;
params.Rs = 0;   % Force singularity — stator resistance = 0 collapses the RL circuit
try
    out2 = sim(MODEL, 'StopTime', '0.01');
    fprintf('Unexpected success.\n');
catch ME
    fprintf('An error occurred while running the simulation and the simulation was terminated:\n\n');
    fprintf('%s\n', ME.message);
    if ~isempty(ME.stack)
        for i = 1:min(length(ME.stack), 6)
            fprintf('Error in %s (line %d)\n', ME.stack(i).name, ME.stack(i).line);
        end
    end
end
params = params_backup;  % Restore

%% === PHASE 3: Repeated RCOND warnings ===
fprintf('\n=== PHASE 3: Repeated RCOND warnings ===\n');
fprintf('Expected proxy output: [x5] dedup + [ORACLE hint]\n\n');
warning('on', 'MATLAB:singularMatrix');
for k = 1:5
    A = [params.Ld 0; 0 params.Lq] * 1e-20;  % near-zero matrix → RCOND warning
    b = [params.lambda; 0];
    x = A \ b;  % triggers Warning: Matrix is close to singular or badly scaled
    fprintf('Iteration %d: norm(x) = %.6f\n', k, norm(x));
end
fprintf('Phase 3 complete.\n');
