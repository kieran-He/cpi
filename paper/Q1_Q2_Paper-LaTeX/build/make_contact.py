from PIL import Image, ImageDraw
from pathlib import Path
files = sorted(Path('paper/Q1_Q2_Paper-LaTeX/build').glob('all-audit-*.png'), key=lambda p: int(p.stem.rsplit('-',1)[1]))
thumbs=[]
for p in files:
    im=Image.open(p).convert('RGB')
    im.thumbnail((280,400))
    canvas=Image.new('RGB',(292,im.height+34),'white')
    canvas.paste(im,((292-im.width)//2,24))
    ImageDraw.Draw(canvas).text((4,4),p.stem.rsplit('-',1)[1],fill='black')
    thumbs.append(canvas)
cols=4
rows=(len(thumbs)+cols-1)//cols
cellw=max(i.width for i in thumbs)
cellh=max(i.height for i in thumbs)
out=Image.new('RGB',(cols*cellw,rows*cellh),(210,210,210))
for i,im in enumerate(thumbs): out.paste(im,((i%cols)*cellw,(i//cols)*cellh))
out.save('paper/Q1_Q2_Paper-LaTeX/build/contact-all-pages.png')
