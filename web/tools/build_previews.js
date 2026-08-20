// 미리보기 빌드 스크립트: templates/*.html + static/*.json → preview-*.html
// (Flask 라우트를 미리보기 파일명으로 바꿔 링크 이동까지 확인 가능)
const ROUTES = {
  '/': 'preview.html',
  '/diagnosis': 'preview-page2.html',
  '/result': 'preview-page3.html',
  '/explore': 'preview-page4.html',
  '/explore/result': 'preview-page5.html',
  '/compare': 'preview-page6.html'
};
const PAGES = [
  ['templates/index.html', 'static/loca_data.json', 'preview.html'],
  ['templates/page2.html', 'static/loca_page2_data.json', 'preview-page2.html'],
  ['templates/page3.html', 'static/loca_page3_data.json', 'preview-page3.html'],
  ['templates/page4.html', 'static/loca_page4_data.json', 'preview-page4.html'],
  ['templates/page5.html', 'static/loca_page5_data.json', 'preview-page5.html'],
  ['templates/page6.html', 'static/loca_page6_data.json', 'preview-page6.html']
];
function localizeLinks(html){
  return html.replace(/(href|action)="(\/[^"]*)"/g, (m, attr, url) => {
    const path = url.split('?')[0];
    const file = ROUTES[path];
    return file ? attr + '="' + file + '"' : m;
  });
}
if (typeof module !== 'undefined') module.exports = { ROUTES, PAGES, localizeLinks };
