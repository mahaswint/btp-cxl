system("mkdir -p eps/")
set term pdfcairo enhanced color size 8,2.8 font ",20"
set output "eps/corr.pdf"

DATAFILE = 'dat/r-l3_stall_skx.csv'

set datafile separator ","

set tic scale .5 out nomirror
set xtics offset 0,.5
set ytics offset .5,0
set xlabel offset 0,.5
set ylabel offset 1,0

set key bottom right samplen .5 width 0 font ",16" offset 1.5,0

# Colors
mtwo   = "#0000FF00" # green
mthree = "#770000FF" # blue
msix   = "#55FF0000" # red

set multiplot layout 1,4

set tmargin 2
set lmargin 5.5
set rmargin 0
set bmargin 3


#-------------------------------------------------------------------------------
# [a] Local DRAM (~90ns): LLC-misses vs. LLC-misses/MLP
#-------------------------------------------------------------------------------
set title "[a] DRAM (90ns)" offset 0,-.5
set ylabel "LLC-Stalls (x10^{12})"
set yrange [0:4.5]
set ytics 2
set xtics 2

plot \
DATAFILE u ($9/(10000000000)):($3/(1000000000000))  w p pt 7 ps 1 lc rgb "gray" t "LLC-miss", \
DATAFILE u ($15/(10000000000)):($3/(1000000000000)) w p pt 9 ps 1 lc rgb msix   t "LLC-miss/MLP"


#-------------------------------------------------------------------------------
# [b] Remote NUMA (~140ns): LLC-misses vs. LLC-misses/MLP
#-------------------------------------------------------------------------------
unset ylabel
set origin .23,0
set yrange [0:6.5]
set title "[b] NUMA (140ns)" offset 0,-.5
set xlabel "Metrics: LLC-miss (●) and PAC=LLC-miss/MLP (▲) (x10^{10})"

plot \
DATAFILE u ($10/(10000000000)):($4/(1000000000000)) w p pt 7 ps 1 lc rgb "gray"  t "LLC-miss", \
DATAFILE u ($16/(10000000000)):($4/(1000000000000)) w p pt 9 ps 1 lc rgb mthree t "LLC-miss/MLP"


#-------------------------------------------------------------------------------
# [c] CXL-emulated (~190ns): LLC-misses vs. LLC-misses/MLP
#-------------------------------------------------------------------------------
unset ylabel
unset xlabel
set origin .46,0
set title "[c] CXL (190ns)" offset 0,-.5

plot \
DATAFILE u ($11/(10000000000)):($5/(1000000000000)) w p pt 7 ps 1 lc rgb "gray" t "LLC-miss", \
DATAFILE u ($17/(10000000000)):($5/(1000000000000)) w p pt 9 ps 1 lc rgb mtwo   t "LLC-miss/MLP"


#-------------------------------------------------------------------------------
# [d] PAC fit lines: 90ns, 140ns, 190ns
#-------------------------------------------------------------------------------
f(x) = a*x
g(x) = c*x
h(x) = e*x

fit f(x) DATAFILE u ($15/(10000000000)):($3/(1000000000000)) via a
fit g(x) DATAFILE u ($16/(10000000000)):($4/(1000000000000)) via c
fit h(x) DATAFILE u ($17/(10000000000)):($5/(1000000000000)) via e

unset ylabel
unset xlabel
unset key
set origin .69,0
set title "[d] PAC Models" offset 0,-.5
set xrange [0:2]
set yrange [0:10]
set xtics 1
set xlabel "LLC-miss/MLP (x10^{10})" offset 0,.5

set label sprintf("90ns: y=%.1fx",  a*100) at graph 0.20, 0.05 font ",18" textcolor rgb "black" rotate by 31
set label sprintf("140ns: y=%.1fx", c*100) at graph 0.3,  0.19 font ",18" textcolor rgb "black" rotate by 49
set label sprintf("190ns: y=%.1fx", e*100) at graph 0.09, 0.3  font ",18" textcolor rgb "black" rotate by 65

plot \
f(x) w l lw 5 lc rgb msix,   \
g(x) w l lw 5 lc rgb mthree, \
h(x) w l lw 5 lc rgb mtwo


unset multiplot
