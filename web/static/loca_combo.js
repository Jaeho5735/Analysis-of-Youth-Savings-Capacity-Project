/* 페이지 안의 내부 링크에 현재 입력을 이어붙인다.

   거주지·근무지는 2페이지에서 한 번 받고 3~6페이지가 계속 쓴다. 그런데 상단
   네비게이션과 일부 버튼은 템플릿·JSON에 링크가 박혀 있어서, 서버에서 고치려면
   그 파일들을 모두 손대야 하고 하나만 놓쳐도 파라미터가 사라진다.
   여기서 한 번에 이어붙이면 링크가 어디에 정의돼 있든 유지된다.

   이미 ?가 붙은 링크는 그 값을 우선하고 빠진 것만 채운다(예: ?dong=청림동). */
(function () {
  var current = new URLSearchParams(window.location.search);
  if (!current.toString()) { return; }

  var KEYS = ['residence', 'workplace', 'deposit', 'rent', 'work_days',
              'depart_time', 'age'];
  var carry = new URLSearchParams();
  KEYS.forEach(function (k) {
    var v = current.get(k);
    if (v) { carry.set(k, v); }
  });
  if (!carry.toString()) { return; }

  document.querySelectorAll('a[href]').forEach(function (a) {
    var href = a.getAttribute('href');
    if (!href || href.charAt(0) !== '/' || href.indexOf('//') === 0) { return; }

    var parts = href.split('?');
    var params = new URLSearchParams(parts[1] || '');
    carry.forEach(function (v, k) {
      if (!params.has(k)) { params.set(k, v); }
    });
    a.setAttribute('href', parts[0] + '?' + params.toString());
  });

  // GET 폼도 마찬가지다. action 의 쿼리스트링은 브라우저가 버리므로
  // hidden 으로 실어야 다음 페이지까지 간다.
  document.querySelectorAll('form[method="get"], form:not([method])').forEach(function (form) {
    carry.forEach(function (v, k) {
      if (form.querySelector('[name="' + k + '"]')) { return; }
      var input = document.createElement('input');
      input.type = 'hidden';
      input.name = k;
      input.value = v;
      form.appendChild(input);
    });
  });
})();

/* 거주지·근무지·후보지 입력 자동완성.

   자유 입력이 기본이고 자동완성은 보조다. resolve_place 가 역명·도로명·지번을
   모두 처리하므로, 목록에 없는 값을 직접 쳐도 통해야 한다.

   행정동 427개를 미리 내려받으면 첫 로딩이 무거워지므로 두 글자부터 서버에
   물어본다. 요청이 실패해도 입력창은 그대로 쓸 수 있다.

   범위 좁히기 - 경로는 거주동별 누적 80% 목적지만 수집해서 모든 조합이 있지
   않다(거주동당 평균 72곳). 전체를 열어두면 사용자가 없는 조합을 고르고
   결과 화면에서야 실패를 알게 되므로, 갈 수 있는 곳만 제안한다.
     data-place="workplace" -> 입력된 거주지에서 갈 수 있는 근무지
     data-place="area"      -> 입력된 근무지로 갈 수 있는 거주지

   마크업:
     <div class="combo" data-combo>
       <input data-place="residence|workplace|area" ...>
       <ul class="combo-list" role="listbox" hidden></ul>
     </div>
*/
(function () {
  function val(selector) {
    var el = document.querySelector(selector);
    return el ? el.value.trim() : '';
  }

  function buildUrl(input, q) {
    var url = '/api/suggest?q=' + encodeURIComponent(q);
    var kind = input.dataset.place;

    if (kind === 'workplace') {
      var home = val('input[data-place="residence"]');
      if (home) { url += '&kind=work&home=' + encodeURIComponent(home); }
    } else if (kind === 'area') {
      // 4·5페이지는 근무지가 hidden 으로 실려 온다
      var work = val('input[name="workplace"]');
      if (work) { url += '&kind=home&work=' + encodeURIComponent(work); }
    }
    return url;
  }

  function setup(box) {
    var input = box.querySelector('input');
    var list = box.querySelector('.combo-list');
    if (!input || !list) { return; }

    var timer = null, items = [], cursor = -1, lastQuery = '';
    var hintEl = box.parentNode.querySelector('.combo-hint')
              || box.parentNode.querySelector('.field-hint');
    var baseHint = hintEl ? hintEl.textContent : '';

    function close() {
      list.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      cursor = -1;
    }

    function paint() {
      Array.prototype.forEach.call(list.children, function (li, i) {
        li.setAttribute('aria-selected', i === cursor ? 'true' : 'false');
      });
    }

    function choose(i) {
      if (!items[i]) { return; }
      input.value = items[i].value;
      lastQuery = items[i].value;
      close();
    }

    function render(data) {
      list.innerHTML = '';
      items = (data && data.items) || [];
      var scoped = !!(data && data.scoped);

      if (hintEl) {
        hintEl.textContent = scoped
          ? '입력하신 조건으로 오갈 수 있는 지역만 보여드려요.'
          : baseHint;
      }

      if (!items.length) {
        var empty = document.createElement('li');
        empty.className = 'empty';
        empty.textContent = scoped
          ? '이 조건으로 오갈 수 있는 지역 중에는 없어요.'
          : '검색 결과가 없어요. 역명이나 주소로 입력해보세요.';
        list.appendChild(empty);
      } else {
        items.forEach(function (item, i) {
          var li = document.createElement('li');
          li.setAttribute('role', 'option');
          var gu = document.createElement('span');
          gu.className = 'gu';
          gu.textContent = (item.label || '').split(' ')[0];
          var dong = document.createElement('span');
          dong.className = 'dong';
          dong.textContent = item.value;
          li.appendChild(gu);
          li.appendChild(dong);
          li.addEventListener('mousedown', function (e) {
            e.preventDefault();
            choose(i);
          });
          list.appendChild(li);
        });
      }
      list.hidden = false;
      input.setAttribute('aria-expanded', 'true');
      cursor = -1;
    }

    input.setAttribute('autocomplete', 'off');
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-expanded', 'false');

    input.addEventListener('input', function () {
      input.classList.remove('invalid');
      var q = input.value.trim();
      if (q.length < 2) { close(); return; }
      if (q === lastQuery) { return; }
      lastQuery = q;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fetch(buildUrl(input, q))
          .then(function (r) { return r.json(); })
          .then(render)
          .catch(close);
      }, 200);
    });

    input.addEventListener('keydown', function (e) {
      if (list.hidden || !items.length) { return; }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        cursor = (cursor + 1) % items.length;
        paint();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        cursor = (cursor - 1 + items.length) % items.length;
        paint();
      } else if (e.key === 'Enter' && cursor >= 0) {
        e.preventDefault();
        choose(cursor);
      } else if (e.key === 'Escape') {
        close();
      }
    });

    input.addEventListener('blur', function () { setTimeout(close, 120); });

    // 거주지를 바꾸면 근무지 추천 범위가 달라지므로 캐시를 비운다
    if (input.dataset.place === 'residence') {
      input.addEventListener('change', function () {
        var w = document.querySelector('input[data-place="workplace"]');
        if (w) { w.dataset.reset = '1'; }
      });
    }
    if (input.dataset.place === 'workplace') {
      input.addEventListener('focus', function () {
        if (input.dataset.reset) {
          lastQuery = '';
          delete input.dataset.reset;
        }
      });
    }
  }

  document.querySelectorAll('[data-combo]').forEach(setup);
})();

/* LOCA 챗봇 패널.

   기존 화면을 건드리지 않는 것이 제약이다. 그래서 이렇게 한다.
     - DOM 을 새로 끼워넣지 않는다. 패널은 body 끝에 position:fixed 로 띄운다.
     - 기존 CSS 파일을 수정하지 않는다. 스타일은 여기서 <style> 로 주입한다.
     - 템플릿에는 data-loca-ask 속성 하나만 추가했다. 태그·클래스·순서는 그대로다.

   질문 칩 세 종류의 상태가 서로 달랐다.
     3·4·6페이지 faq 칩  : <div> 라 링크도 아니었다. 눌러도 아무 일이 없었다.
     6페이지 "왜 그렇게 판단했어?" : href="#" 라 화면만 맨 위로 튀었다.
     5페이지 채팅바 칩    : name="q" 로 폼을 제출해 화면이 시연값으로 돌아갔다.
   세 경우를 여기서 한꺼번에 받는다. 뒤 두 개는 preventDefault 로 막는다.

   스크립트가 죽어도 화면은 예전 동작으로 물러설 뿐 깨지지 않는다. */
(function () {
  var PAGE_PATHS = {
    '/result': 3, '/explore': 4, '/explore/result': 5, '/compare': 6
  };
  if (!(window.location.pathname in PAGE_PATHS)) { return; }

  /* 화면 가운데에 띄운다. 오른쪽 아래에 두면 답변이 길어질 때 세로로
     자라면서 화면 절반을 덮고, 시선이 본문과 패널 사이를 오간다.
     가운데에 두면 위치가 고정되고 배경이 고르게 눌린다. */
  var STYLE = [
    '.loca-ask-backdrop{position:fixed;inset:0;background:rgba(20,40,38,.42);',
    'opacity:0;transition:opacity .18s;z-index:9998;}',
    '.loca-ask-backdrop.on{opacity:1;}',
    '.loca-ask{position:fixed;left:50%;top:50%;',
    'transform:translate(-50%,-48%);opacity:0;',
    'width:min(560px,calc(100vw - 32px));max-height:min(72vh,620px);',
    'display:flex;flex-direction:column;background:#fff;border-radius:20px;',
    'box-shadow:0 24px 64px rgba(20,60,55,.26);z-index:9999;overflow:hidden;',
    'transition:transform .18s ease-out,opacity .18s ease-out;',
    'font-size:15px;line-height:1.65;}',
    '.loca-ask.on{transform:translate(-50%,-50%);opacity:1;}',
    '.loca-ask-head{flex:0 0 auto;display:flex;align-items:center;',
    'justify-content:space-between;padding:15px 20px;',
    'border-bottom:1px solid #eef2f1;font-weight:700;color:#1f3b37;}',
    '.loca-ask-close{border:0;background:none;font-size:22px;line-height:1;',
    'cursor:pointer;color:#6b807c;padding:2px 6px;}',
    '.loca-ask-body{flex:1 1 auto;min-height:0;overflow-y:auto;',
    'padding:18px 20px 22px;}',
    '.loca-ask-q{color:#3f5c57;font-weight:600;margin:0 0 12px;}',
    '.loca-ask-a{color:#24413d;margin:0;white-space:pre-wrap;}',
    '@media (max-width:600px){.loca-ask{width:calc(100vw - 24px);',
    'max-height:80vh;}}'
  ].join('');

  var panel = null, backdrop = null, qEl = null, aEl = null, seq = 0;
  // CPU 추론은 한 번에 20초~몇 분이 걸린다. 두 번 눌리면 모델이 두 벌
  // 돌면서 둘 다 타임아웃으로 죽는다(로그에 1.2초 간격 중복 호출이 있었다).
  // 그래서 답이 올 때까지 새 요청을 보내지 않는데, 이때 아무 반응도 하지
  // 않으면 사용자 눈에는 버튼이 고장난 것으로 보인다. 창은 반드시 띄우고
  // 진행 중이라고 알린다.
  // busy 가 어떤 이유로든 풀리지 않으면 버튼이 영구히 죽으므로 감시 타이머로
  // 강제 해제한다. 조용히 안 눌리는 상태가 가장 나쁘다.
  var busy = false, watchdog = null;

  function setBusy(on) {
    busy = on;
    clearTimeout(watchdog);
    if (on) {
      watchdog = setTimeout(function () { busy = false; }, 260000);
    }
  }
  var scrollLocked = '';

  function build() {
    var style = document.createElement('style');
    style.textContent = STYLE;
    document.head.appendChild(style);

    backdrop = document.createElement('div');
    backdrop.className = 'loca-ask-backdrop';
    backdrop.addEventListener('click', close);

    panel = document.createElement('div');
    panel.className = 'loca-ask';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');

    var head = document.createElement('div');
    head.className = 'loca-ask-head';
    var title = document.createElement('span');
    title.textContent = 'LOCA에게 물어보기';
    var closeBtn = document.createElement('button');
    closeBtn.className = 'loca-ask-close';
    closeBtn.type = 'button';
    closeBtn.setAttribute('aria-label', '닫기');
    closeBtn.textContent = '×';
    closeBtn.addEventListener('click', close);
    head.appendChild(title);
    head.appendChild(closeBtn);

    var body = document.createElement('div');
    body.className = 'loca-ask-body';
    qEl = document.createElement('p');
    qEl.className = 'loca-ask-q';
    aEl = document.createElement('p');
    aEl.className = 'loca-ask-a';
    body.appendChild(qEl);
    body.appendChild(aEl);

    panel.appendChild(head);
    panel.appendChild(body);
    document.body.appendChild(backdrop);
    document.body.appendChild(panel);
  }

  function close() {
    if (!panel) { return; }
    seq++;                                  // 진행 중인 응답을 버린다
    panel.classList.remove('on');
    backdrop.classList.remove('on');
    document.body.style.overflow = scrollLocked;
    setTimeout(function () {
      panel.style.display = 'none';
      backdrop.style.display = 'none';
    }, 180);
  }

  function open(question) {
    if (!panel) { build(); }
    scrollLocked = document.body.style.overflow;
    document.body.style.overflow = 'hidden';   // 뒤 배경이 같이 스크롤되지 않게
    panel.style.display = 'flex';
    backdrop.style.display = 'block';
    // 다음 프레임에 켜야 transition 이 먹는다
    requestAnimationFrame(function () {
      panel.classList.add('on');
      backdrop.classList.add('on');
    });
    qEl.textContent = question;
    aEl.textContent = '화면의 값을 읽고 설명을 만들고 있어요. 조금 걸릴 수 있어요...';
  }

  function params() {
    var out = {};
    new URLSearchParams(window.location.search).forEach(function (v, k) {
      out[k] = v;
    });
    return out;
  }

  function send(question) {
    if (busy) {
      // 무시하되 창은 띄운다. 반응이 없으면 고장으로 보인다.
      open(question);
      aEl.textContent = '앞선 질문에 답하는 중이에요. 잠시 후 다시 눌러주세요.';
      return;
    }
    var mine = ++seq;
    open(question);
    setBusy(true);

    fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: window.location.pathname,
        question: question,
        params: params()
      })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (mine !== seq) { return; }   // 그 사이 다른 칩을 눌렀거나 닫혔다
        // 폴백이라는 사실은 답변 문장 자체가 이미 밝히고 있다.
        // 여기서 같은 말을 한 번 더 붙이면 두 줄이 겹쳐 읽힌다.
        aEl.textContent = d.answer || '답을 만들지 못했어요.';
      })
      .catch(function () {
        if (mine !== seq) { return; }
        aEl.textContent = '지금은 답변을 불러오지 못했어요. 잠시 후 다시 시도해주세요.';
      })
      .finally(function () { setBusy(false); });
  }

  document.addEventListener('click', function (e) {
    var el = e.target.closest ? e.target.closest('[data-loca-ask]') : null;
    if (!el) { return; }
    // 5페이지 채팅바 칩은 폼 제출 버튼이고, 6페이지 버튼은 href="#" 다.
    // 둘 다 여기서 막지 않으면 페이지가 새로 뜬다.
    e.preventDefault();
    try {
      send(el.getAttribute('data-loca-ask') || '');
    } catch (err) {
      // 여기서 터지면 이후 클릭이 전부 죽는다. 콘솔에 남기고 넘어간다.
      console.error('[LOCA] 질문 전송 실패', err);
      setBusy(false);
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { close(); return; }
    if (e.key !== 'Enter' && e.key !== ' ') { return; }
    // faq 칩은 <div> 라 키보드로는 눌리지 않았다. 최소한만 보탠다.
    var el = e.target.closest ? e.target.closest('[data-loca-ask]') : null;
    if (!el || el.tagName === 'BUTTON' || el.tagName === 'A') { return; }
    e.preventDefault();
    send(el.getAttribute('data-loca-ask') || '');
  });

  // 채팅바의 보내기 버튼은 name 이 없어서 아무 값 없이 폼을 제출했고,
  // 그 결과 /explore/result 가 시연 화면으로 되돌아갔다. 제출 자체를 막는다.
  document.querySelectorAll('form.chat-input').forEach(function (form) {
    form.addEventListener('submit', function (e) { e.preventDefault(); });
  });
})();
