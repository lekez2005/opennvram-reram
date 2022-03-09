.subckt ms_flop_clk_buf din dout dout_bar clk vdd gnd
*.ipin clk
*.opin dout_bar
*.opin dout
*.iopin vdd
*.iopin gnd
*.ipin din
XM1 clk_buf clk_bar gnd gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.36 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM8 clk_buf clk_bar vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=0.9 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM2 clk_bar clk gnd gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.36 nf=1  
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM3 clk_bar clk vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=0.9 nf=1  
+ sa=0 sb=0 sd=0 mult=1 m=1 
X1 din clk_buf vdd gnd lout lout_bar clk_bar dlatch
X2 lout_bar clk_bar vdd gnd dout_bar dout clk_buf dlatch
.ends

.subckt dlatch  din clk vdd gnd dout dout_bar clk_bar
*.ipin din
*.iopin vdd
*.iopin gnd
*.ipin clk
*.ipin clk_bar
*.opin dout_bar
*.opin dout
XM1 dout dout_bar gnd gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.61 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM2 dout_bar int gnd gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.61 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM3 int clk dout gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.36 nf=1  
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM5 int clk_bar dout vdd sky130_fd_pr__pfet_01v8 L=0.15 W=0.6 nf=1  
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM4 int clk_bar din gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.36 nf=1  
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM6 int clk din vdd sky130_fd_pr__pfet_01v8 L=0.15 W=0.6 nf=1  
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM7 dout_bar int vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=1.22 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM8 dout dout_bar vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=1.22 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
.ends
