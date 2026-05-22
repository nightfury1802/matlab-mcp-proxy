%% run_pmsm_foc_doe.m
% 15-point speed/torque DOE sweep — tests progress line compression (R08)
% Grid: 5 speed × 3 torque points
%
% Expected proxy output: head(2) + "[11 lines omitted]" + tail(2)

MODEL = 'PMSM_FOC_Proxy_Test';
if ~bdIsLoaded(MODEL)
    load_system(MODEL);
end

% Ensure params are available — load defaults if run standalone
if ~exist('params', 'var')
    params.p      = 4;
    params.lambda = 0.1012;
    params.Ts     = 1e-4;
    params.T_max  = 107.63;
    fprintf('params not found in workspace — using defaults\n');
end

speeds_rpm = [1000 2000 3000 4500 6000];
torques_Nm = [50   80   107];
total_pts  = length(speeds_rpm) * length(torques_Nm);

results = struct('speed',  cell(1, total_pts), ...
                 'tref',   cell(1, total_pts), ...
                 'tss',    cell(1, total_pts), ...
                 'status', cell(1, total_pts));
k = 0;

for omega_rpm = speeds_rpm
    for T_ref = torques_Nm
        k = k + 1;
        iq_cmd = T_ref / (1.5 * params.p * params.lambda);
        set_param([MODEL '/iq_ref'], 'Value', num2str(iq_cmd));

        try
            out = sim(MODEL, 'StopTime', '0.3');
            T_ss    = out.torque_out(end);
            err_pct = abs(T_ss - T_ref) / T_ref * 100;
            if err_pct > 5
                status = 'FAIL';
            else
                status = 'PASS';
            end
        catch
            T_ss   = NaN;
            status = 'ERROR';
        end

        results(k).speed  = omega_rpm;
        results(k).tref   = T_ref;
        results(k).tss    = T_ss;
        results(k).status = status;

        fprintf('DOE point %3d/%d: omega=%4d rpm, Tref=%3d Nm -> T=%.2f Nm [%s]\n', ...
                k, total_pts, omega_rpm, T_ref, T_ss, status);
    end
end

n_pass  = sum(strcmp({results.status}, 'PASS'));
n_fail  = sum(strcmp({results.status}, 'FAIL'));
n_error = sum(strcmp({results.status}, 'ERROR'));

fprintf('\nDOE complete: %d/%d PASS, %d FAIL, %d ERROR\n', ...
        n_pass, total_pts, n_fail, n_error);
