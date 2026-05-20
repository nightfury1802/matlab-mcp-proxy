% Scenario: long fprintf progress output (DOE sweep)
% Compression rule tested: R08 (compress_progress_lines)
% Expected reduction: ~79%
% Run via: evaluate_matlab_code with this script content
omegas = [1000 2000 3000 4000 6000];
Trefs  = [50 80 107];
k = 0;
for omega = omegas
    for Tref = Trefs
        k = k + 1;
        T_sim = Tref * (1 - 0.01*randn);   % mock result
        fprintf('DOE point %3d/15: omega=%4d rpm, Tref=%3d Nm -> T=%.2f Nm [PASS]\n', ...
                k, omega, Tref, T_sim);
    end
end
fprintf('Done. %d points complete.\n', k);
