import sys
import zipfile
from lxml import etree

NS = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main', 'p': 'http://schemas.openxmlformats.org/presentationml/2006/main'}
for filename in sys.argv[1:]:
    print('\nFILE', filename)
    with zipfile.ZipFile(filename) as z:
        names = sorted((n for n in z.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml')), key=lambda n: int(n.split('slide')[-1].split('.')[0]))
        print('SLIDES', len(names))
        for name in names:
            print(' ', name)
            root = etree.fromstring(z.read(name))
            for sp in root.xpath('//p:sp', namespaces=NS):
                c = sp.find('p:nvSpPr/p:cNvPr', NS)
                sid = c.get('id') if c is not None else '?'
                sname = c.get('name') if c is not None else '?'
                texts = sp.xpath('.//a:t/text()', namespaces=NS)
                if texts:
                    print('  ', sid, repr(sname), repr(' '.join(texts)))
            print('  PICTURES', len(root.xpath('//p:pic', namespaces=NS)))
