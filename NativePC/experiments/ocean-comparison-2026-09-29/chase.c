#define _GNU_SOURCE
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

static uint64_t ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC_RAW, &t);
    return (uint64_t)t.tv_sec * 1000000000ULL + t.tv_nsec;
}
static uint64_t rng(uint64_t *s) {
    *s ^= *s << 13; *s ^= *s >> 7; *s ^= *s << 17;
    return *s;
}
__attribute__((noinline)) static uint64_t chase(volatile uint64_t *p, uint64_t n) {
    uint64_t at = 0;
    for (uint64_t i=0; i<n; ++i) at = p[at * 8];
    return at;
}
int main(int argc, char **argv) {
    const size_t bytes = 2*1024*1024, lines = bytes/64;
    uint64_t steps = argc > 2 ? strtoull(argv[2],NULL,0) : 1000000;
    if (!steps || argc < 2) return 2;
    int fd = -1;
    void *mapping;
    if (!strcmp(argv[1],"ram")) mapping=mmap(NULL,bytes,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    else {
        fd=open(argv[1],O_RDWR);
        if(fd<0){perror("open dax");return 1;}
        mapping=mmap(NULL,bytes,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
    }
    if(mapping==MAP_FAILED){perror("mmap");return 1;}
    uint64_t *order=malloc(lines*sizeof(*order));
    if(!order)return 1;
    for(size_t i=0;i<lines;i++)order[i]=i;
    uint64_t seed=0x123456789abcdefULL;
    for(size_t i=lines-1;i>0;i--){size_t j=rng(&seed)%(i+1);uint64_t t=order[i];order[i]=order[j];order[j]=t;}
    volatile uint64_t *p=mapping;
    uint64_t init_start=ns();
    for(size_t i=0;i<lines;i++)p[order[i]*8]=order[(i+1)%lines];
    uint64_t init_ns=ns()-init_start;
    size_t zero_pos=0;while(order[zero_pos])zero_pos++;
    uint64_t expected=order[(zero_pos+steps%lines)%lines];
    if(chase(p,lines)!=0){fprintf(stderr,"warmup mismatch\n");return 1;}
    printf("BEGIN mode=%s bytes=%zu steps=%llu init_ns=%llu\n",argv[1],bytes,(unsigned long long)steps,(unsigned long long)init_ns);
    fflush(stdout);
    for(int r=0;r<5;r++) {
        uint64_t start=ns();uint64_t result=chase(p,steps);uint64_t elapsed=ns()-start;
        printf("RESULT mode=%s rep=%d steps=%llu elapsed_ns=%llu result=%llu expected=%llu ok=%d\n",argv[1],r+1,(unsigned long long)steps,(unsigned long long)elapsed,(unsigned long long)result,(unsigned long long)expected,result==expected);
        fflush(stdout);if(result!=expected)return 1;
    }
    munmap(mapping,bytes);if(fd>=0)close(fd);free(order);return 0;
}
