# Code Metrics Tool

* Used for computing code quality, complexity, and architectural metrics on source code (aligned with **ASPICE 4.0 SWE.4** and **HIS OEM Standards**).
* By default, the metrics reports are generated inside the target's build directory under a **`code_metrics`** directory.
* The user can customize the directory in which the metrics report is placed via the `report_out_path` configuration option.
* Other configurations regarding this tool are specified in the target options within the project YAML build configuration.

---

## Configuration Example

Each threshold can be configured either as a dictionary with `value` and `blocker` (`true`/`false`), or as a plain scalar number (which defaults to `blocker: false`):

```yaml
- !target
  name: YSP_WIN_GCC
  tools:
  - gcc
  - fsmgen
  - datagen
  - console_log
  - absint
  - code_metrics
  type: program
  options:
  - *gcc_options
  - absint:
      dax: project@yzk_platform.dax
      report_out_path: target@__absint__
  - code_metrics:
      report_out_path: target@__cm__
      # HIS Complexity & Size Thresholds
      cc_threshold:
        value: 15
        blocker: true
      nloc_threshold:
        value: 100
        blocker: false
      pline_threshold:
        value: 200
        blocker: false
      min_comment_ratio:
        value: 10
        blocker: false
      min_file_comment_ratio:
        value: 10
        blocker: false
      stmt_threshold:
        value: 50
        blocker: false
      vocf_threshold:
        value: 4.0
        blocker: false
      
      # HIS Control Flow & Architecture Thresholds
      param_threshold:
        value: 5
        blocker: false
      return_threshold:
        value: 1
        blocker: false
      nesting_depth_threshold:
        value: 4
        blocker: false
      goto_threshold:
        value: 0
        blocker: true
      calling_threshold: 10
      calls_threshold: 7
      path_threshold: 200
      rec_threshold:
        value: 0
        blocker: true
      dead_code_threshold:
        value: 0
        blocker: true
      
      # OEM Quality Audit & Coding Standard Thresholds
      call_depth_threshold: 6
      file_lines_threshold: 1200
      static_declarations_threshold: 20
```

---

## Configuration Parameters

All parameters are specified as child keys under the `code_metrics` section of the target options in the YAML configuration. Every threshold accepts either a scalar (`int`/`float`) or a `{value: <limit>, blocker: <bool>}` mapping.

| Parameter | Type | Default | Metric / Standard | Description |
| :--- | :---: | :---: | :--- | :--- |
| `report_out_path` | `str` | *target build dir* | General | Output directory for the generated XML, HTML, and JUnit reports. Relative paths are resolved against project root. |
| `cc_threshold` | `int` | `20` | HIS `v(G)` / cyclomatic | Maximum allowed classic McCabe Cyclomatic Complexity per function ($M = 1 + \text{decision points}$, excluding `&&`/`||` short-circuit branches). Evaluates decision density. Recommended OEM limit: `<= 15`. |
| `nloc_threshold` | `int` | `200` | HIS `COMF` / function size | Maximum allowed Non-Comment Lines of Code per function. Recommended limit: `<= 100`. |
| `pline_threshold` | `int` | `200` | AbsInt `PLINE` / file NLOC | Maximum allowed Non-Comment Lines of Code per file (excluding blank lines and pure comments; also accepts alias `file_nloc_threshold`). |
| `min_comment_ratio` | `float` | `10.0` | HIS `CDRP` / function comments | Minimum allowed function comment density ratio (%), including header/Doxygen comments immediately above the function and inline body comments, calculated as: $\frac{\text{comments}}{\text{NLOC} + \text{comments}} \times 100$. |
| `min_file_comment_ratio` | `float` | `10.0` | HIS `CDRP` / file comments | Minimum allowed file comment density ratio (%) across the entire translation unit (all file-level and function-level comments), calculated as: $\frac{\text{comments}}{\text{NLOC} + \text{comments}} \times 100$. |
| `param_threshold` | `int` | `5` | HIS `PARAM` / stability | Maximum allowed formal parameters per function. Evaluates interface clarity and coupling. |
| `return_threshold` | `int` | `1` | HIS `RET` / stability | Maximum allowed return points per function (MISRA C single exit point compliance). |
| `nesting_depth_threshold` | `int` | `4` | HIS `LEVEL` / testability | Maximum control structure nesting depth (`if`, `for`, `while`, `switch`). OEM limit: `<= 7`. |
| `stmt_threshold` | `int` | `50` | HIS `STMT` / analysability | Maximum executable statements per function body. |
| `vocf_threshold` | `float` | `4.0` | HIS `VOCF` / analysability | Maximum allowed HIS Language Scope / Vocabulary Frequency per function, calculated as $\frac{N_1 + N_2}{n_1 + n_2}$ (total lexical tokens divided by distinct lexical tokens). |
| `goto_threshold` | `int` | `0` | HIS `GOTO` / changeability | Maximum allowed `goto` jump statements per function (MISRA C Rule 15.1 forbids `goto`). |
| `calling_threshold` | `int` | `10` | HIS `CALLING` / Fan-In | Maximum number of different functions calling this function across the build. Measures architectural coupling. |
| `calls_threshold` | `int` | `7` | HIS `CALLS` / Fan-Out | Maximum distinct functions called by this function. Measures unit test isolation complexity. |
| `path_threshold` | `int` | `1000` | HIS `PATH` / stability | Maximum static execution paths through the function. OEM limit: `<= 200`. |
| `rec_threshold` | `int` | `0` | HIS `REC` / stability | Maximum recursive calls (direct or indirect). Automotive safety standards forbid recursion. |
| `dead_code_threshold` | `int` | `0` | HIS `DEAD` / stability | Maximum unreachable / dead code statements following unconditional termination. |
| `call_depth_threshold` | `int` | `6` | OEM Call Graph Depth | Maximum call graph invocation depth starting from this function through its call hierarchy. OEM limit: `<= 6`. |
| `file_lines_threshold` | `int` | `1200` | OEM File Size | Maximum total line count (including comments and blank lines) in a single translation unit. OEM limit: `<= 1200`. |
| `static_declarations_threshold` | `int` | `20` | OEM Static Declarations | Maximum number of unique `static` declarations (variables and functions) in a file. OEM limit: `<= 20`. |

---

## ASPICE 4.0 SWE.4 & HIS Standard Alignment

The tool enforces metrics derived from the **Hersteller Initiative Software (HIS)** source code metrics consortium and satisfies the verification requirements of **ASPICE 4.0 Process SWE.4 (Software Detailed Design and Unit Construction)**:

| HIS Metric Code | Metric Name | Recommended Range | Scope | Quality Objective |
| :--- | :--- | :---: | :---: | :--- |
| **`v(G)`** | Cyclomatic Complexity | $1 \le v(G) \le 10$ (Warn: $11-15$, Fail: $> 15$) | Function | Low control flow branching, high testability |
| **`COMF`** | Lines of Code (NLOC) | $1 \le \text{NLOC} \le 100$ | Function | Readability, concise modular units |
| **`PLINE`** | File Lines of Code (PLINE) | $1 \le \text{PLINE} \le 200$ | File | Translation unit non-comment code size (AbsInt PLINE) |
| **`CDRP`** | Comment Density Ratio | $\ge 8.0\%$ (Default: $10.0\%$) | Function / File | Self-documenting code base (includes function header comments) |
| **`PARAM`** | Number of Parameters | $0 \le \text{PARAM} \le 5$ | Function | Minimal function interface coupling |
| **`RET`** | Number of Return Points | $\text{RET} = 1$ | Function | Deterministic exit point, easy resource cleanup |
| **`LEVEL`** | Max Nesting Depth | $1 \le \text{LEVEL} \le 4$ (OEM: $\le 7$) | Function | Comprehensibility and unit test path coverage |
| **`STMT`** | Executable Statements | $1 \le \text{STMT} \le 50$ | Function | Single responsibility principle |
| **`VOCF`** | Language Scope (Vocabulary Frequency) | $1.0 \le \text{VOCF} \le 4.0$ | Function | Low token repetition, maintainable function scope |
| **`GOTO`** | GOTO Statements | $\text{GOTO} = 0$ | Function | Structured programming compliance |
| **`CALLING`** | Fan-In (Callers) | $0 \le \text{CALLING} \le 10$ | Function | Modular dependency management |
| **`CALLS`** | Fan-Out (Callees) | $0 \le \text{CALLS} \le 7$ | Function | Encapsulation and reduced ripple effects |
| **`PATH`** | Static Path Count | $1 \le \text{PATH} \le 200$ | Function | Verifiable exhaustive path testing |
| **`REC`** | Recursion Count | $\text{REC} = 0$ | Function | Bounded stack depth and timing determinism |
| **`DEAD`** | Unreachable Statements | $\text{DEAD} = 0$ (OEM: $\le 20$) | Function / File | Elimination of dead code |
| **`DEPTH`** | Call Graph Depth | $1 \le \text{DEPTH} \le 6$ | Function | Predictable call hierarchies |
| **`FILE_LINES`** | Total File Lines | $\le 1200$ | File | Manageable file modularity |
| **`STATIC_DECL`** | Static Declarations | $\le 20$ | File | Encapsulation, thread safety, bounded state |
| **`IF_ELSE`** | IF Without ELSE | $0$ | Function | Complete decision branches (MISRA 15.7) |
| **`UNUSED_VAR`** | Non-used Variables | $0$ | Function | Clean allocations, no redundant tokens (MISRA 2.2) |

---

## Output Artifacts

Running the `code_metrics` tool produces three main artifacts:

1. **XML Metrics Report (`<target>.xml`)**:
   Full machine-readable hierarchy detailing every analyzed function and source file with all computed metrics (CCN, NLOC, parameters, tokens, paths, dead code, call depth, file lines, static declarations, etc.).
2. **Interactive HTML Dashboard (`<target>.html`)**:
   Standalone, self-contained dashboard (no external CDN or internet connection required). Contains:
   - Executive quality KPIs and pass/fail rate badges.
   - Interactive Cyclomatic Complexity and NLOC distribution bar charts.
   - Sortable, searchable Function and File tables with active filter chips.
   - CSV export capability for custom spreadsheet analysis.
   - Threshold Limits configuration reference table.
3. **CI/CD JUnit Report (`junit_report.xml`)**:
   Standard JUnit XML test suite format mapping functions and files to test cases. Any threshold violation generates a `<failure>` element with human-readable diagnostic messages, allowing continuous integration pipelines (Jenkins, GitLab CI, Azure DevOps) to fail builds or display test results natively.

---

## Waf Pre-Build Quality Gate & `blocker` Configuration

When running `code_metrics` through Waf:
1. **Pre-Build Execution**:
   * `code_metrics` tasks (`cc_xml` $\rightarrow$ `cc_xml2html` $\rightarrow$ `cc_xml2junit`) run in pre-build phases (`phase=1, 2, 3`) and are scheduled **before** any C/C++ compilation or linking tasks (`c`, `cxx`, `asm`, `cprogram`, `cstlib`, `cshlib`).
   * If you have a standalone `type: code_metrics` target in your YAML alongside binary targets, building any binary target (even with `--targets=<binary_target>`) automatically runs the `code_metrics` target first before compiling.
   * Building the `code_metrics` target independently (`waf build --targets=<code_metrics_target>`) runs **only** `code_metrics` without triggering compilation.
2. **YAML `value` & `blocker` Quality Gate**:
   * All three reports (`<target>.xml`, `<target>.html`, and `junit_report.xml`) are always generated first with complete violation counts.
   * **Per-threshold `blocker`**: Configure any threshold with `value` and `blocker: true` (or `blocker: false`). If a threshold with `blocker: true` has `> 0` violations, Waf logs a `RED` blocker summary and immediately fails the build (`exit code 1`) before compiling any source files.
   * **Backward-compatible scalar syntax**: Specifying a plain number (e.g. `stmt_threshold: 50`) sets `value: 50` with `blocker: false`.
   * **Global master switch**: You can also set `code_metrics_blocker: true` (or `blocker: true`) directly under `code_metrics:` in YAML to make all active thresholds blockers by default, and override specific thresholds with `blocker: false`.

---

## Standalone CLI Usage

The core metric analyzer can also be executed directly via command line without the Waf build system:

```bash
python hfcca.py [options] [PATH or FILE] ...
```

### Supported CLI Flags

* `--xml=<output_file.xml>`: Write full metric results to XML format.
* `--input=<file_list.txt>`: Read target file paths line-by-line from a text file.
* `-e <pattern>`, `--exclude=<pattern>`: Exclude files matching regex patterns (e.g., `-e ".*test.*"`).
* `-t <num>`, `--working-threads=<num>`: Multi-threaded parallel file analysis (default: CPU core count).
* `-C`, `--no-preprocessor-count`: Ignore preprocessor directive lines (`#if`, `#define`, `#include`) in line count.
* `-s <threshold>`, `--sort=<threshold>`: Filter functions exceeding a specific complexity threshold.
