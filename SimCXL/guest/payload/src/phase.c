/* Wrapper used only after switching from KVM/atomic boot to timing simulation. */
#include <stdio.h>
#include <string.h>
#include <gem5/simcxl_phase.h>

int main(int argc, char **argv)
{
    if (argc != 3 || strlen(argv[2]) >= 256) {
        fprintf(stderr, "usage: phase begin|end NAME (under 256 bytes)\n");
        return 2;
    }
    if (!strcmp(argv[1], "begin")) simcxl_phase_begin(argv[2]);
    else if (!strcmp(argv[1], "end")) simcxl_phase_end(argv[2]);
    else return 2;
    return 0;
}
