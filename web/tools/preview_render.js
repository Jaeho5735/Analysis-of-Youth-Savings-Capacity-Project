// Local preview renderer: renders the Flask/Jinja templates with their JSON data
// into standalone preview-*.html files (for viewing without running Flask).
// Supports: {{ dotted.path }}, {{ obj['key'] }}, {% for x in list %}, {% if %}/{% elif %}/{% else %},
// {% include 'partials/x.html' %} (through the partials map), url_for('static', filename=...).
var PATH = "[\\w.$'\\[\\]]+";

function get(obj, path){
  return String(path)
    .replace(/\['([^']+)'\]/g, '.$1')
    .split('.')
    .reduce(function(o, k){ return o == null ? undefined : o[k]; }, obj);
}

function evalCond(expr, ctx){
  expr = expr.trim();
  var m = expr.match(new RegExp('^(' + PATH + ')\\s*==\\s*(?:\'([^\']*)\'|(' + PATH + '))$'));
  if(m){
    var l = get(ctx, m[1]);
    var r = m[2] !== undefined ? m[2] : get(ctx, m[3]);
    return l === r;
  }
  if(/^not\s+loop\.last$/.test(expr)) return !ctx.$last;
  if(expr === 'loop.last') return !!ctx.$last;
  return !!get(ctx, expr);
}

function resolveIncludes(tpl, partials, depth){
  if(depth > 5) return tpl;
  return tpl.replace(/{%\s*include\s+'([^']+)'\s*%}/g, function(m, p){
    return resolveIncludes(partials[p] != null ? partials[p] : '', partials, depth + 1);
  });
}

function render(tpl, ctx, partials){
  if(partials) tpl = resolveIncludes(tpl, partials, 0);
  var tagSrc = '{%\\s*(for\\s+\\w+\\s+in\\s+' + PATH + '|endfor|if\\s+[^%]+?|elif\\s+[^%]+?|else|endif)\\s*%}';
  var forSrc = '{%\\s*(for\\s+\\w+\\s+in\\s+' + PATH + '|endfor)\\s*%}';
  var tagRe = new RegExp(tagSrc, 'g');
  var out = '', i = 0, m;

  while((m = tagRe.exec(tpl))){
    var tag = m[1].trim();

    if(tag.indexOf('for ') === 0){
      var depth = 1, j = tagRe.lastIndex, inner = '', s;
      var scan = new RegExp(forSrc, 'g');
      scan.lastIndex = j;
      while((s = scan.exec(tpl))){
        if(s[1].trim().indexOf('for ') === 0) depth++;
        else {
          depth--;
          if(depth === 0){ inner = tpl.slice(j, s.index); tagRe.lastIndex = scan.lastIndex; break; }
        }
      }
      out += tpl.slice(i, m.index);
      var head = tag.match(new RegExp('^for\\s+(\\w+)\\s+in\\s+(' + PATH + ')$'));
      var list = get(ctx, head[2]) || [];
      out += list.map(function(item, k){
        var scope = Object.assign({}, ctx);
        scope[head[1]] = item;
        scope.$index = k;
        scope.$last = k === list.length - 1;
        return render(inner, scope);
      }).join('');
      i = tagRe.lastIndex;
      continue;
    }

    if(tag.indexOf('if ') === 0){
      var d = 1, start = tagRe.lastIndex, body = '', t;
      var ifScan = /{%\s*(if\s+[^%]+?|endif)\s*%}/g;
      ifScan.lastIndex = start;
      while((t = ifScan.exec(tpl))){
        if(t[1].trim().indexOf('if ') === 0) d++;
        else {
          d--;
          if(d === 0){ body = tpl.slice(start, t.index); tagRe.lastIndex = ifScan.lastIndex; break; }
        }
      }
      out += tpl.slice(i, m.index);

      var branches = [], cur = tag.slice(3).trim(), last = 0, d2 = 0, b;
      var brRe = /{%\s*(if\s+[^%]+?|endif|elif\s+[^%]+?|else)\s*%}/g;
      while((b = brRe.exec(body))){
        var bt = b[1].trim();
        if(bt.indexOf('if ') === 0) d2++;
        else if(bt === 'endif') d2--;
        else if(d2 === 0 && (bt.indexOf('elif') === 0 || bt === 'else')){
          branches.push([cur, body.slice(last, b.index)]);
          cur = bt.indexOf('elif') === 0 ? bt.slice(4).trim() : null;
          last = brRe.lastIndex;
        }
      }
      branches.push([cur, body.slice(last)]);

      var chosen = '';
      for(var n = 0; n < branches.length; n++){
        if(branches[n][0] === null || evalCond(branches[n][0], ctx)){ chosen = branches[n][1]; break; }
      }
      out += render(chosen, ctx);
      i = tagRe.lastIndex;
      continue;
    }
  }
  out += tpl.slice(i);

  out = out.replace(/{{\s*url_for\('static',\s*filename\s*=\s*([^)]+)\)\s*}}/g, function(mm, arg){
    var parts = arg.split('~').map(function(piece){
      piece = piece.trim();
      var lit = piece.match(/^'([^']*)'$/);
      if(lit) return lit[1];
      var v = get(ctx, piece);
      return v == null ? '' : String(v);
    });
    return 'static/' + parts.join('');
  });

  out = out.replace(new RegExp('{{\\s*(' + PATH + ')\\s*}}', 'g'), function(mm, p){
    var v = get(ctx, p);
    return v == null ? '' : String(v).replace(/\n/g, '<br>');
  });

  return out;
}

if (typeof module !== 'undefined') module.exports = { render, resolveIncludes };
