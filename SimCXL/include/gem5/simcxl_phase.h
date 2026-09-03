/* CXL-only phase markers. Link the guest with libm5. */
#ifndef GEM5_SIMCXL_PHASE_H
#define GEM5_SIMCXL_PHASE_H
#include <stdint.h>
#include <gem5/m5ops.h>

static inline void simcxl_phase_begin(const char *name)
{
    m5_work_begin((uint64_t)(uintptr_t)name, UINT64_C(0x53494d43584c));
}

static inline void simcxl_phase_end(const char *name)
{
    m5_work_end((uint64_t)(uintptr_t)name, UINT64_C(0x53494d43584c));
}
#endif
