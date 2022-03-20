.subckt write_driver_mux_buffer vdd gnd data en mask data_bar bl br
*.PININFO vdd:B gnd:B data:I en:I mask:I data_bar:I bl:O br:O
x1 data bl_p bl_n en mask data_bar br_p br_n gnd vdd write_driver_mux_logic
XM5 bl bl_n gnd gnd sky130_fd_pr__nfet_01v8 L=0.15 W=3.6 nf=1  
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM1 br br_n gnd gnd sky130_fd_pr__nfet_01v8 L=0.15 W=3.6 nf=1  
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM7 br br_p vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=9 nf=2  
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM2 bl bl_p vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=9 nf=2  
+ sa=0 sb=0 sd=0 mult=1 m=1 
.ends
