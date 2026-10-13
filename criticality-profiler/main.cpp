#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

// Phases execute in sequence; lanes within a phase execute concurrently.
// Rows within a lane add compute time and dependent memory-access latency.
struct Event {
    std::string phase, lane, page;
    double accesses, compute_ns;
};
using Trace = std::vector<Event>;
using Placement = std::set<std::string>;

double runtime(const Trace& trace, const Placement& fast, double fast_ns,
               double slow_ns) {
    std::map<std::string, std::map<std::string, double>> phases;
    for (const auto& e : trace)
        phases[e.phase][e.lane] += e.compute_ns + e.accesses *
            (fast.count(e.page) ? fast_ns : slow_ns);
    double total = 0;
    for (const auto& phase : phases) {
        double longest = 0;
        for (const auto& lane : phase.second)
            longest = std::max(longest, lane.second);
        total += longest;
    }
    return total;
}

struct Score { std::string page; double frequency, criticality; };
std::vector<Score> profile(const Trace& trace, double fast_ns, double slow_ns) {
    std::map<std::string, double> counts;
    for (const auto& e : trace)
        if (e.accesses > 0) counts[e.page] += e.accesses;
    const double baseline = runtime(trace, {}, fast_ns, slow_ns);
    std::vector<Score> scores;
    for (const auto& entry : counts) {
        // Isolated counterfactual: how much faster is the entire trace if
        // only this page moves to fast memory?
        scores.push_back({entry.first, entry.second,
            baseline - runtime(trace, {entry.first}, fast_ns, slow_ns)});
    }
    return scores;
}

Placement select(std::vector<Score> scores, size_t capacity, bool critical) {
    std::sort(scores.begin(), scores.end(), [critical](const Score& a, const Score& b) {
        double av = critical ? a.criticality : a.frequency;
        double bv = critical ? b.criticality : b.frequency;
        if (av != bv) return av > bv;
        if (a.frequency != b.frequency) return a.frequency > b.frequency;
        return a.page < b.page;
    });
    Placement result;
    for (size_t i = 0; i < std::min(capacity, scores.size()); ++i)
        result.insert(scores[i].page);
    return result;
}

std::vector<std::string> fields(const std::string& line) {
    std::vector<std::string> result;
    std::stringstream stream(line);
    std::string value;
    while (std::getline(stream, value, ',')) {
        auto first = value.find_first_not_of(" \t\r");
        auto last = value.find_last_not_of(" \t\r");
        result.push_back(first == std::string::npos ? "" : value.substr(first, last-first+1));
    }
    return result;
}
double number(const std::string& value) {
    size_t consumed = 0;
    double result = std::stod(value, &consumed);
    if (consumed != value.size() || !std::isfinite(result) || result < 0)
        throw std::runtime_error("Expected a finite nonnegative number: " + value);
    return result;
}
Trace read_trace(const std::string& path) {
    std::ifstream input(path);
    if (!input) throw std::runtime_error("Cannot open " + path);
    Trace result;
    std::string line;
    size_t line_number = 0;
    bool header = false;
    while (std::getline(input, line)) {
        ++line_number;
        if (line.find_first_not_of(" \t\r") == std::string::npos ||
            line[line.find_first_not_of(" \t\r")] == '#') continue;
        auto f = fields(line);
        if (!header) {
            if (f != std::vector<std::string>{"phase", "lane", "page", "accesses", "compute_ns"})
                throw std::runtime_error("Expected CSV header phase,lane,page,accesses,compute_ns");
            header = true;
            continue;
        }
        try {
            if (f.size() != 5 || f[0].empty() || f[1].empty() || f[2].empty())
                throw std::runtime_error("Expected five nonempty fields");
            double count = number(f[3]);
            if (std::floor(count) != count) throw std::runtime_error("accesses must be an integer");
            result.push_back({f[0], f[1], f[2], count, number(f[4])});
        } catch (const std::exception& e) {
            throw std::runtime_error(path + ":" + std::to_string(line_number) + ": " + e.what());
        }
    }
    if (result.empty()) throw std::runtime_error("Trace is empty: " + path);
    return result;
}

std::string names(const Placement& pages) {
    std::string result;
    for (const auto& page : pages) result += (result.empty() ? "" : ", ") + page;
    return result.empty() ? "(none)" : result;
}
void compare(const std::string& label, const Trace& training, const Trace& evaluation,
             size_t capacity, double fast_ns, double slow_ns) {
    auto scores = profile(training, fast_ns, slow_ns);
    auto frequency = select(scores, capacity, false);
    auto criticality = select(scores, capacity, true);
    double baseline = runtime(evaluation, {}, fast_ns, slow_ns);
    double freq = runtime(evaluation, frequency, fast_ns, slow_ns);
    double crit = runtime(evaluation, criticality, fast_ns, slow_ns);
    std::cout << "\n" << label << " | fast slots=" << capacity
              << " | latency fast/slow=" << fast_ns << "/" << slow_ns << " ns\n"
              << "Training profile (criticality = isolated runtime reduction, ns):\n"
              << "page\taccesses\tcriticality_ns\n";
    for (const auto& s : scores)
        std::cout << s.page << '\t' << s.frequency << '\t' << s.criticality << '\n';
    std::cout << "Frequency placement: " << names(frequency) << '\n'
              << "Criticality placement: " << names(criticality) << '\n'
              << "Evaluation runtime ns: all-slow=" << baseline
              << ", frequency=" << freq << ", criticality=" << crit << '\n'
              << "Criticality reduction vs frequency: "
              << (freq > 0 ? 100 * (freq - crit) / freq : 0) << "%\n";
}

int main(int argc, char** argv) {
    try {
        double fast_ns = 10, slow_ns = 100;
        size_t capacity = 1;
        std::string train_path, eval_path;
        bool demo = argc == 1;
        for (int i = 1; i < argc; ++i) {
            std::string option = argv[i];
            if (option == "--help") {
                std::cout << "Usage: profiler [--demo] [--trace training.csv] [--eval heldout.csv]\n"
                          << "                [--capacity pages] [--fast-ns N] [--slow-ns N]\n";
                return 0;
            }
            if (option == "--demo") { demo = true; continue; }
            if (i + 1 >= argc) throw std::runtime_error("Missing value for " + option);
            std::string value = argv[++i];
            if (option == "--trace") train_path = value;
            else if (option == "--eval") eval_path = value;
            else if (option == "--fast-ns") fast_ns = number(value);
            else if (option == "--slow-ns") slow_ns = number(value);
            else if (option == "--capacity") {
                if (value.empty() || value.find_first_not_of("0123456789") != std::string::npos)
                    throw std::runtime_error("capacity must be a nonnegative integer");
                auto parsed = std::stoull(value);
                capacity = static_cast<size_t>(parsed);
                if (capacity != parsed) throw std::runtime_error("capacity is too large");
            } else throw std::runtime_error("Unknown option: " + option);
        }
        if (!(fast_ns > 0 && slow_ns >= fast_ns))
            throw std::runtime_error("Require 0 < fast-ns <= slow-ns");
        if (!eval_path.empty() && train_path.empty())
            throw std::runtime_error("--eval requires --trace");
        if (!demo && train_path.empty()) throw std::runtime_error("Specify --demo or --trace");
        std::cout << std::fixed << std::setprecision(2)
                  << "Analytical memory placement profiler; modeled time, not measured application time.\n";
        if (demo) {
            Trace win{{"1","memory","hot",10,0}, {"1","compute","unused",0,2000},
                      {"2","serial","critical",4,0}};
            Trace tie{{"1","serial","hot",10,0}, {"1","serial","cold",4,0}};
            Trace loss{{"1","left","A",6,0}, {"1","right","B",6,0},
                       {"2","serial","C",4,0}};
            compare("Demo: frequent accesses hidden by parallel compute",win,win,1,fast_ns,slow_ns);
            compare("Control: fully serial memory accesses",tie,tie,1,fast_ns,slow_ns);
            compare("Limitation: two tied bottlenecks need joint promotion",loss,loss,2,fast_ns,slow_ns);
        }
        if (!train_path.empty()) {
            auto training = read_trace(train_path);
            auto evaluation = eval_path.empty() ? training : read_trace(eval_path);
            compare(eval_path.empty() ? "CSV: same-trace evaluation" : "CSV: held-out evaluation",
                    training,evaluation,capacity,fast_ns,slow_ns);
        }
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << '\n';
        return 1;
    }
}
