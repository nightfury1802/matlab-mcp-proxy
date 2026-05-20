% Scenario: repeated singular matrix warnings (one per iteration)
% Compression rule tested: R01 (compress_repeated_warnings)
% Expected reduction: ~59%
% Run via: evaluate_matlab_code with this script content
warning('on','all');
results = zeros(1,10);
for k = 1:10
    A = [1 2; 2 4] + 1e-18*rand(2);   % near-singular matrix
    b = [1;1];
    results(k) = norm(A\b);            % triggers RCOND warning each iteration
end
fprintf('Mean result: %.4f\n', mean(results));
