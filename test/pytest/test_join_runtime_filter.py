"""Pytest twin of native_join_runtime_filter.sh."""
import re

def _has_runtime_filter(c):
 with c.cursor() as x:
  x.execute("SELECT current_setting('pgcolumnar.enable_join_runtime_filter', true)")
  return x.fetchone()[0] is not None

def _plan(c,sql,on=None):
 with c.cursor() as x:
  if on is not None and _has_runtime_filter(c):
   x.execute(f"SET pgcolumnar.enable_join_runtime_filter={'on' if on else 'off'}")
  x.execute("SET max_parallel_workers_per_gather=0")
  x.execute("SET enable_nestloop=off")
  x.execute("SET enable_mergejoin=off")
  x.execute("EXPLAIN(ANALYZE,TIMING off,SUMMARY off)"+sql)
  return "\n".join(r[0] for r in x.fetchall())
def _v(p,n):
 m=re.search(re.escape(n)+r": ([0-9]+)",p);return int(m.group(1)) if m else -1
def test_serial_join_runtime_filter(pgc_conn,expect):
 with pgc_conn.cursor() as c:
  c.execute("CREATE TABLE d(k int);INSERT INTO d SELECT g FROM generate_series(8001,8200)g;INSERT INTO d VALUES(8100),(NULL);CREATE TABLE f(k int,p text)USING pgcolumnar;SELECT pgcolumnar.set_options('f',stripe_row_limit=>1000);INSERT INTO f SELECT g,repeat(md5(g::text),8)FROM generate_series(1,20000)g;CREATE TABLE h AS SELECT * FROM f;ANALYZE d;ANALYZE f")
 sql="SELECT count(*),sum(f.k),sum(length(f.p))FROM f JOIN d ON f.k=d.k"
 b=_plan(pgc_conn,sql,False);p=_plan(pgc_conn,sql,True)
 expect.num(b.count("Hash Join"),1,"baseline core Hash Join")
 expect.num(_v(b,"Columnar Chunk Groups Read"),20,"baseline reads all groups")
 expect.num(p.count("Columnar Runtime Filter Coordinator"),1,"plan has runtime coordinator")
 expect.num(p.count("Columnar Runtime Filter Build Tap"),1,"plan has build tap")
 expect.num(p.count("Hash Join"),1,"plan retains core Hash Join")
 expect.num(_v(p,"Runtime Filter Build Rows"),201,"build rows omit NULL")
 expect.num(p.count("Runtime Filter Ready: yes"),1,"filter ready before scan")
 expect.num(_v(p,"Runtime Filter Groups Removed"),19,"clustered groups removed")
 expect.num(_v(p,"Columnar Chunk Groups Read"),1,"clustered reads fewer groups")
 with pgc_conn.cursor() as c:
  c.execute("SELECT current_setting(pgcolumnar.enable_join_runtime_filter,true)")
  if c.fetchone()[0] is not None:c.execute("SET pgcolumnar.enable_join_runtime_filter=on")
  c.execute(sql);a=c.fetchone()
  if c.execute("SELECT current_setting(pgcolumnar.enable_join_runtime_filter,true)").fetchone()[0] is not None:c.execute("SET pgcolumnar.enable_join_runtime_filter=off")
  c.execute(sql);o=c.fetchone()
  c.execute("SELECT count(*),sum(h.k),sum(length(h.p))FROM h JOIN d ON h.k=d.k");h=c.fetchone()
 expect.ordered_rows([a],[o],"runtime answer equals off")
 expect.ordered_rows([a],[h],"runtime answer equals heap")
 for name,s in [("LEFT refusal","SELECT count(*)FROM f LEFT JOIN d ON f.k=d.k"),("SEMI refusal","SELECT count(*)FROM f WHERE EXISTS(SELECT 1 FROM d WHERE d.k=f.k)"),("ANTI refusal","SELECT count(*)FROM f WHERE NOT EXISTS(SELECT 1 FROM d WHERE d.k=f.k)"),("CROSS refusal","SELECT count(*)FROM f JOIN(SELECT k::bigint k FROM d)x ON f.k=x.k")]:
  expect.num(_plan(pgc_conn,s,True).count("Columnar Runtime Filter Coordinator"),0,name)
