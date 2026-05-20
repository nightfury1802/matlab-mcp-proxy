% Scenario: deep call stack error
% Compression rule tested: R02 (compress_stack_trace)
% Expected reduction: ~40%
% NOTE: Save this as a file and run via run_matlab_file, not evaluate_matlab_code
% (nested function definitions require a file, not inline eval)
function top_level()
    A = zeros(3);    % singular matrix — will cause error in level3
    result = level1(A);
end

function result = level1(x)
    result = level2(x);
end

function result = level2(x)
    result = level3(x);
end

function result = level3(x)
    result = x \ eye(size(x));   % will error: singular matrix
end

top_level();
