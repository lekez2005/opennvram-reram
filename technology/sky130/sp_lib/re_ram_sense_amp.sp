.subckt re_ram_sense_amp bl br dout dout_bar en gnd sampleb vclamp vclampp vdd vref
*.ipin vclamp
*.ipin vclampp
*.ipin sampleb
*.iopin vdd
*.ipin vref
*.ipin en
*.opin dout
*.opin dout_bar
*.iopin br
*.iopin gnd
*.iopin bl
XM1 vdata vclamp bl gnd sky130_fd_pr__nfet_01v8 L=0.15 W=1.44 nf=4
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM2 vdata vclampp net1 vdd sky130_fd_pr__pfet_01v8 L=0.15 W=0.9 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM3 net1 sampleb vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=0.9 nf=1  
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM4 net3 vdata net2 gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.6 nf=1  
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM5 dout vref net2 gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.6 nf=1  
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM6 net2 en gnd gnd sky130_fd_pr__nfet_01v8 L=0.15 W=1.2 nf=2
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM7 dout net3 vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=1.2 nf=1  
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM8 net3 net3 vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=1.2 nf=1  
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM9 dout_bar dout gnd gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.72 nf=2
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM10 dout_bar dout vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=1.44 nf=2
+   sa=0 sb=0 sd=0 mult=1 m=1 
.ends

