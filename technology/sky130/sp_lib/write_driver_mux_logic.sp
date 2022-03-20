.subckt write_driver_mux_logic mask en data data_bar bl_p bl_n br_p br_n gnd vdd
*.PININFO mask:I en:I data:I data_bar:I bl_p:O bl_n:O br_p:O br_n:O gnd:B vdd:B
XM4 mask_en_bar en net1 gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.72 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM1 net1 mask gnd gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.72 nf=1  
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM2 mask_en_bar en vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=0.9 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM3 mask_en_bar mask vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=0.9 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM5 mask_en mask_en_bar gnd gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.72 nf=1
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM7 br_p data_bar net2 gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.72 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM8 net2 mask_en gnd gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.72 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM9 br_p data_bar vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=0.9 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM10 br_p mask_en vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=0.9 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM11 bl_p data net3 gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.72 nf=1  
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM12 net3 mask_en gnd gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.72 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM13 bl_p data vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=0.9 nf=1  
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM14 bl_p mask_en vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=0.9 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM16 br_n mask_en_bar gnd gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.72 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM18 br_n data_bar net4 vdd sky130_fd_pr__pfet_01v8 L=0.15 W=1.8 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM15 br_n data_bar gnd gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.72 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM17 net4 mask_en_bar vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=1.8 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM19 bl_n mask_en_bar gnd gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.72 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM20 bl_n data net5 vdd sky130_fd_pr__pfet_01v8 L=0.15 W=1.8 nf=1  
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM21 bl_n data gnd gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.72 nf=1  
+ sa=0 sb=0 sd=0 mult=1 m=1 
XM22 net5 mask_en_bar vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=1.8 nf=1 
+   sa=0 sb=0 sd=0 mult=1 m=1 
XM6 mask_en mask_en_bar vdd vdd sky130_fd_pr__pfet_01v8 L=0.15 W=1.5 nf=1
+   sa=0 sb=0 sd=0 mult=1 m=1 
.ends
** flattened .save nodes
