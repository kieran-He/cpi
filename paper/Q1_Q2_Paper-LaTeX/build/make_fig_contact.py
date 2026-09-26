from PIL import Image, ImageDraw
from pathlib import Path
base=Path('figures/q1_paper')
paths=[base/'q1_fig02_mass_volume.png',base/'q1_fig03_area_demand.png',base/'q1_fig04_candidate_reduction.png',base/'q1_fig06_frontier_cardinality.png',base/'q1_fig07_capacity_envelope.png',base/'q1_fig08_baseline_pareto.png',base/'q1_fig09_sortie_manifest.png',base/'q1_fig10_energy_sensitivity.png',Path('figures/raw_q2_mass_volume_priority.png'),Path('figures/raw_q2_desired_windows.png'),Path('figures/process_q2_pool_by_model.png'),Path('figures/process_q2_route_stop_counts.png'),Path('figures/process_q2_drone_schedule.png'),Path('figures/process_q2_pareto_archive.png'),Path('figures/result_q2_delivery_windows.png'),Path('figures/result_q2_fleet_energy.png')]
thumbs=[]
for i,p in enumerate(paths,1):
 im=Image.open(p).convert('RGB'); im.thumbnail((430,300))
 cell=Image.new('RGB',(450,338),'white'); cell.paste(im,((450-im.width)//2,24)); ImageDraw.Draw(cell).text((7,5),f'{i}: {p.name}',fill='black'); thumbs.append(cell)
cols=3; rows=(len(thumbs)+cols-1)//cols; sheet=Image.new('RGB',(cols*450,rows*338),(210,210,210))
for i,im in enumerate(thumbs): sheet.paste(im,((i%cols)*450,(i//cols)*338))
sheet.save('paper/Q1_Q2_Paper-LaTeX/build/contact-selected-figs.png')
