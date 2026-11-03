import os, sys
from lxml import etree
def xml2html(xml_report_file, html_report_file, xslt):
    
    source = etree.parse(xml_report_file)

    xslt = etree.parse(xslt)
    transform = etree.XSLT(xslt)
    result = transform(source)
    
    result.write(html_report_file,  method='html', pretty_print='True')

if __name__ == '__main__':
    import sys
    xml2html(sys.argv[1], sys.argv[2], sys.argv[3])
    