// The scene, its shader programs: sky, ice, the Sparks, the beam, the sparks and the glow, compiled once.
'use strict';
// The programs of the scene: compiles every shader once and hands them to the parts that draw with them.
function scenePrograms(shared) {  // seam
  const { gl } = shared;  // seam
  const floats = !!(gl.getExtension('EXT_color_buffer_float') || gl.getExtension('EXT_color_buffer_half_float'));
  const COLOR = floats ? gl.RGBA16F : gl.RGBA8, TEXEL = floats ? gl.HALF_FLOAT : gl.UNSIGNED_BYTE;

  // Compiles and links one shader program and looks up its uniforms; a shader that does not compile throws, and the scene falls back.
  const compile = (vs, fs, attrs) => {
    const p = gl.createProgram();
    for (const [type, src] of [[gl.VERTEX_SHADER, vs], [gl.FRAGMENT_SHADER, fs]]) {
      const s = gl.createShader(type);
      gl.shaderSource(s, '#version 300 es\nprecision highp float;\n' + src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      gl.attachShader(p, s);
    }
    attrs.forEach((name, i) => gl.bindAttribLocation(p, i, name));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    const u = {};
    const count = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < count; i++) { const n = gl.getActiveUniform(p, i).name.replace('[0]', ''); u[n] = gl.getUniformLocation(p, n); }
    return { p, u };
  };

  const NOISE = `
    float hash(vec2 p){ p=fract(p*vec2(123.34,456.21)); p+=dot(p,p+45.32); return fract(p.x*p.y); }
    float noise(vec2 p){ vec2 i=floor(p), f=fract(p); f=f*f*(3.-2.*f); return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y); }
    float fbm(vec2 p){ float a=.5, s=0.; for(int i=0;i<4;i++){ s+=a*noise(p); p=mat2(1.6,1.2,-1.2,1.6)*p; a*=.5; } return s; }`;
  const FULL = `in vec2 p; out vec2 v; void main(){ v=p*.5+.5; gl_Position=vec4(p,0.,1.); }`;

  /* the sky is a function of direction, so the ice can mirror it */
  const skyP = compile(`in vec2 p; out vec3 ray; uniform vec3 camR, camU, camF; uniform vec2 tanH, shift; uniform float flip;
      void main(){ vec2 n=p-shift; ray=camF+camR*n.x*tanH.x+camU*n.y*tanH.y; ray.y*=flip; gl_Position=vec4(p,0.,1.); }`,
    `in vec3 ray; out vec4 o; uniform vec3 glowDir; uniform float t, act, studioDim; ${NOISE}
    void main(){
      vec3 d=normalize(ray);
      float h=d.y, up=max(h,0.);
      vec3 c=mix(vec3(.02,.034,.115),vec3(.0022,.0034,.018),smoothstep(0.,.55,up));
      c+=vec3(.05,.035,.16)*exp(-up*8.);
      vec3 sum=vec3(0.);
      float dith=hash(gl_FragCoord.xy*.73+fract(t));
      for(int i=0;i<12;i++){
        float f=(float(i)+dith)/12.;
        float k=(1.+f*.72)/(up*1.25+.16);
        vec2 q=d.xz*k*.9+vec2(t*.014,0.);
        vec2 wob=vec2(noise(q*.55+vec2(t*.021,3.1)),noise(q*.55+vec2(7.3,-t*.017)));
        float b=noise((q+wob*1.25)*vec2(.8,.34));
        float rib=pow(1.-abs(b*2.-1.),14.);
        vec3 tint=mix(vec3(.05,1.,.6),vec3(.5,.2,1.),smoothstep(.0,.62,f));
        tint=mix(tint,vec3(1.,.22,.55),smoothstep(.74,1.,f)*.65);
        sum+=tint*rib*pow(1.-f,2.1);
      }
      c+=sum*smoothstep(.0,.05,up)*(1.-smoothstep(.55,.95,up))*(.1+.26*act);
      float a=atan(d.x,-d.z);
      float m1=1.-abs(2.*noise(vec2(a*3.1+9.,2.))-1.), m2=1.-abs(2.*noise(vec2(a*8.7+3.,5.))-1.), m3=1.-abs(2.*noise(vec2(a*31.,1.))-1.);
      float ridge=.012+.075*m1*m1*m1+.03*m2*m2+.0065*m3;
      float rock=1.-smoothstep(ridge-.0016,ridge+.0016,h);
      vec3 stone=vec3(.0014,.002,.0065)+vec3(.22,.15,.62)*.07*smoothstep(ridge-.06,ridge,h);
      vec3 bl=d-glowDir;
      o=vec4(mix(c,stone,rock)*(1.-studioDim*.62)+vec3(.13,.17,.3)*exp(-dot(bl,bl)*5.)*studioDim,1.);
    }`, ['p']);
  /* copies a picture as it is, from one target to the next */
  const copyP = compile(FULL, `in vec2 v; out vec4 o; uniform sampler2D tex; void main(){ o=texture(tex,v); }`, ['p']);

  /* the stars: points of light that twinkle, only above the horizon */
  const starP = compile(`in vec4 p; uniform mat4 vp; uniform float flip, sc, t; out float A;
      void main(){ vec3 d=p.xyz; A=(.6+.4*sin(t*(.5+fract(p.x*91.)*1.3)+p.y*47.))*smoothstep(.12,.32,d.y); d.y*=flip;
        vec4 q=vp*vec4(d,0.); gl_Position=vec4(q.xy,q.w*.9999,q.w); gl_PointSize=p.w*sc; }`,
    `in float A; out vec4 o; void main(){ float d=length(gl_PointCoord-.5)*2.; o=vec4(vec3(.85,.9,1.)*A*exp(-d*d*4.)*(1.-smoothstep(.8,1.,d))*1.5,0.); }`, ['p']);

  /* the ice: it mirrors the scene, glows under each Spark and carries the waves */
  const iceP = compile(`in vec2 p; uniform mat4 vp; out vec3 W; void main(){ W=vec3(p.x,0.,p.y); gl_Position=vp*vec4(W,1.); }`,
    `in vec3 W; out vec4 o; uniform vec3 eye; uniform vec2 res; uniform sampler2D refl; uniform float t, act, beam, charge, reveal, studioDim;
    uniform vec4 glow[8]; uniform vec3 tone[8]; uniform int nodes; uniform vec4 waves[6]; ${NOISE}
    void main(){
      vec2 w=W.xz; float r=length(w), far=length(eye-W); vec3 v=(eye-W)/far;
      vec2 q=w*7.+vec2(t*.11,-t*.08);
      float n0=noise(q);
      vec2 g=vec2(noise(q+vec2(.22,0.))-n0,noise(q+vec2(0.,.22))-n0)*.16/(1.+far*far*.05);
      vec3 front=vec3(0.);
      for(int i=0;i<6;i++){
        vec4 a=waves[i];
        if(a.w<=0.) continue;
        vec2 e=w-a.xy; float d=length(e)+1e-4, s=d-a.z*1.05;
        g+=e/d*exp(-s*s*38.)*a.w*cos(s*46.)*.16;
        front+=vec3(.5,.45,1.)*exp(-s*s*260.)*a.w*.9;
      }
      vec2 uv=gl_FragCoord.xy/res+g*vec2(.05,.16);
      float b=.0035+.004*smoothstep(1.,6.,far);
      vec3 R=(texture(refl,uv).rgb*2.+texture(refl,uv+vec2(0.,b)).rgb+texture(refl,uv-vec2(0.,b)).rgb+texture(refl,uv+vec2(b*.7,0.)).rgb+texture(refl,uv-vec2(b*.7,0.)).rgb)/6.;
      float F=mix(.05,.9,pow(1.-max(v.y,0.),4.));
      vec3 c=vec3(.0012,.0016,.005)+R*F;
      float k=(r-1.)*9.;
      c+=vec3(.36,.3,1.)*exp(-k*k)*(.008+.07*act)*reveal;
      float a=atan(w.y,w.x);
      float tick=(1.-smoothstep(.02,.09,abs(fract(a*90./6.28318)-.5)))*(1.-smoothstep(.0,.014,abs(r-1.46)));
      float dial=(1.-smoothstep(.0,.004,abs(r-1.46)))+(1.-smoothstep(.0,.003,abs(r-.62)))*.6;
      c+=vec3(.5,.5,.95)*(tick*.16+dial*.07)*reveal;
      for(int i=0;i<nodes;i++){ float d=distance(w,glow[i].xy); c+=tone[i]*exp(-d*d*20.)*glow[i].z*.7; }
      vec2 dir=w/max(r,1e-3);
      float spin=t*(.25+1.6*beam);
      float sw=fbm(dir*(1.5+r*3.)+vec2(spin,-spin*.7)+r*2.4);
      float plate=smoothstep(.6,.14,r)*smoothstep(.0,.1,r);
      c+=mix(vec3(.4,.28,1.),vec3(.35,1.,.86),sw)*pow(sw,2.2)*plate*(beam*3.6+charge*2.4);
      float rip=pow(.5+.5*sin(r*46.-t*(3.+9.*beam)),10.)*smoothstep(.62,.1,r)*smoothstep(.02,.09,r);  // the beam strikes: rings run outward
      c+=vec3(.5,.8,1.)*rip*beam*.6;
      c+=vec3(.8,.9,1.)*exp(-r*r*900.)*(beam*5.+charge*.4)+vec3(.6,.7,1.)*exp(-r*r*60.)*(beam*1.1+charge*.3);
      o=vec4((c+front)*(1.-studioDim*.55),1.);
    }`, ['p']);

  /* the lanes of the ring: light that runs along each link with its traffic */
  const laneP = compile(`in vec3 p; in vec3 d; uniform mat4 vp; uniform float flip; out vec3 D; out vec3 W;
      void main(){ vec3 q=p; q.y*=flip; W=q; D=d; gl_Position=vp*vec4(q,1.); }`,
    `in vec3 D; in vec3 W; out vec4 o; uniform vec4 lanes[32]; uniform float reveal, sweep, burst, quiet;
    void main(){
      vec4 L=lanes[int(D.z+.5)];
      float s=D.y, core=exp(-s*s*60.), halo=exp(-s*s*5.);
      float x=fract(D.x*3.2-L.x+D.z*.37), comet=pow(x,10.)*(1.-smoothstep(.96,1.,x)), e=L.y;
      vec3 tint=mix(vec3(.46,.38,1.),vec3(.2,.95,.75),L.z);
      vec3 c=tint*(halo*(.015+.28*e)+core*(.12+.8*e))+(tint*.4+vec3(.7))*comet*core*(.1+14.*e);
      float ang=atan(W.z,W.x)/6.28318+.5;
      c*=1.-smoothstep(reveal-.03,reveal,ang);
      c+=vec3(.92,.88,1.)*pow(fract(ang-sweep),30.)*burst*core*8.;
      o=vec4(c*quiet,0.);
    }`, ['p', 'd']);

  /* a Spark as a plain box, lit by its power, its heat and the beam: what stands there while the real model is not loaded */
  const sparkP = compile(`in vec3 p; in vec3 n; uniform mat4 vp; uniform vec3 at; uniform float yaw, flip; out vec3 W; out vec3 N; out vec3 L; out vec3 P;
      void main(){ float c=cos(yaw), s=sin(yaw); vec3 q=vec3(c*p.x+s*p.z,p.y,-s*p.x+c*p.z)+at; q.y*=flip;
        L=p; P=n; W=q; N=vec3(c*n.x+s*n.z,n.y*flip,-s*n.x+c*n.z); gl_Position=vp*vec4(q,1.); }`,
    `in vec3 W; in vec3 N; in vec3 L; in vec3 P; out vec4 o; uniform vec3 eye, tone; uniform float heat, live, hot, power, t, act, beam, flip; ${NOISE}
    vec2 h2(vec2 p){ return fract(sin(vec2(dot(p,vec2(127.1,311.7)),dot(p,vec2(269.5,183.3))))*43758.5453); }
    float cells(vec2 p){ vec2 i=floor(p), f=fract(p); float d=9.; for(int y=-1;y<=1;y++) for(int x=-1;x<=1;x++){ vec2 g=vec2(x,y), r=g+h2(i+g)-f; d=min(d,dot(r,r)); } return sqrt(d); }
    vec3 env(vec3 r){
      float up=max(r.y,0.), down=max(-r.y,0.);
      vec3 c=mix(vec3(.05,.05,.11),vec3(.012,.013,.04),smoothstep(.0,.7,up));
      c+=mix(vec3(.12,1.,.7),vec3(.55,.3,1.),r.x*.5+.5)*pow(noise(vec2(r.x*2.4+t*.04,r.z*1.3+1.)),2.5)*smoothstep(.02,.4,up)*(.1+.5*act);
      return c+vec3(.5,.4,1.)*down*down*(.03+.5*act);
    }
    void main(){
      if(W.y*flip<0.) discard;
      vec3 n=normalize(N), v=normalize(eye-W);
      float front=step(.92,abs(P.z)), top=step(.92,P.y);
      if(top>.5) n=normalize(n+vec3((noise(vec2(L.x*520.,L.z*9.))-.5)*.03,0.,0.));
      float nv=max(dot(n,v),.001);
      vec3 f0=vec3(.99,.74,.40), g=f0+(1.-f0)*pow(1.-nv,5.), r=reflect(-v,n);
      vec3 key=normalize(vec3(-.4,1.,.55));
      vec3 c=g*env(r)*1.2+f0*vec3(1.,.86,.62)*(.05+.26*max(dot(n,key),0.));
      c+=g*pow(max(dot(n,normalize(key+v)),0.),120.)*3.+g*pow(1.-nv,3.)*.28;
      c+=g*pow(max(dot(r,normalize(vec3(0.,.55,0.)-W)),0.),18.)*(beam*5.+.06);
      if(front>.5){
        vec2 q=L.xy*210.;
        q+=.35*vec2(noise(q*.21),noise(q*.21+5.));
        float pore=mix(.42,1.-smoothstep(.16,.44,cells(q)),clamp(1.4-fwidth(q.y)*1.4,0.,1.));
        c=mix(c*1.25,c*.05+mix(vec3(1.,.62,.24),tone,heat)*(.01+power*power*7.),pore);
      }
      c=mix(vec3(dot(c,vec3(.33))),c,live)*mix(.25,1.,live);
      c+=vec3(.55,.5,1.)*hot*(.04+pow(1.-nv,2.)*.9);
      o=vec4(c,1.);
    }`, ['p', 'n']);

  /* the real Spark, part by part. H is the height of a point in the closed machine: the scan front runs along it */
  const MODEL_VS = `in vec3 p; in vec3 n; in vec2 uv; in vec2 uv2; uniform mat4 vp; uniform vec3 at, part; uniform float yaw, flip, scale, spin, home; out vec3 W; out vec3 N; out vec2 U; out vec2 V; out float H;
      void main(){ float k=cos(spin), m=sin(spin); vec3 a=vec3(k*p.x+m*p.z,p.y,-m*p.x+k*p.z), b=vec3(k*n.x+m*n.z,n.y,-m*n.x+k*n.z);
        H=a.y+home; vec3 o=(a+part)*scale; float c=cos(yaw), s=sin(yaw); vec3 q=vec3(c*o.x+s*o.z,o.y,-s*o.x+c*o.z)+at; q.y*=flip;
        U=uv; V=uv2; W=q; N=vec3(c*b.x+s*b.z,b.y*flip,-s*b.x+c*b.z); gl_Position=vp*vec4(q,1.); }`;
  const modelP = compile(MODEL_VS,
    `in vec3 W; in vec3 N; in vec2 U; in vec2 V; in float H; out vec4 o;
    uniform vec3 eye, tone, color, emit; uniform vec2 mr; uniform ivec4 has; uniform sampler2D tBase, tMR, tNorm, tEmit, tLight;
    uniform float heat, live, hot, power, t, act, beam, flip, scan, back, dim, inspect; ${NOISE}
    vec3 env(vec3 r, float e){
      float up=max(r.y,0.), down=max(-r.y,0.);
      vec3 c=mix(vec3(.05,.05,.11),vec3(.012,.013,.04),smoothstep(.0,.7,up));
      c+=mix(vec3(.12,1.,.7),vec3(.55,.3,1.),r.x*.5+.5)*pow(noise(vec2(r.x*2.4+t*.04,r.z*1.3+1.)),2.5)*smoothstep(.02,.4,up)*(.1+.5*act)*(1.-e*.7);
      return c+vec3(.5,.4,1.)*down*down*(.03+.5*act);
    }
    vec3 studio(vec3 r, float e){  // soft boxes: what a product photo reflects
      float s=.04+e*.7;
      vec3 c=vec3(.016,.019,.028)+vec3(.05,.055,.07)*max(r.y,0.);
      vec2 q=r.xz/max(r.y,.08)-vec2(-.25,.3);
      float top=smoothstep(1.+s,1.-s,abs(q.x)/1.15)*smoothstep(1.+s,1.-s,abs(q.y)/.8)*smoothstep(0.,.25,r.y);
      c+=vec3(1.,.97,.93)*top*(3.4-2.2*e);
      float side=smoothstep(.22+s,.22-s,abs(atan(r.z,r.x)+2.2))*smoothstep(.55+s,.55-s,abs(r.y-.05));
      c+=vec3(.9,.95,1.)*side*(1.6-e);
      return c+vec3(.06,.05,.12)*max(-r.y,0.);
    }
    float lobe(vec3 n, vec3 v, vec3 l, float e){  // the highlight one light leaves on a surface this rough
      vec3 h=normalize(l+v); float nl=max(dot(n,l),0.), nv=max(dot(n,v),.001), a=e*e, a2=a*a, nh=max(dot(n,h),0.), d=nh*nh*(a2-1.)+1.;
      float k=(e+1.)*(e+1.)/8., G=(nl/(nl*(1.-k)+k+1e-3))*(nv/(nv*(1.-k)+k+1e-3));
      return a2/max(3.14159*d*d,1e-5)*G/max(4.*nl*nv,.02)*nl;
    }
    vec3 bump(vec3 n, vec3 m){
      vec3 dx=dFdx(W), dy=dFdy(W); vec2 ux=dFdx(U), uy=dFdy(U);
      vec3 a=cross(dy,n), b=cross(n,dx), T=a*ux.x+b*uy.x, B=a*ux.y+b*uy.y;
      float s=max(dot(T,T),dot(B,B));
      return s>1e-16?normalize(m.x*T/sqrt(s)+m.y*B/sqrt(s)+m.z*n):n;
    }
    void main(){
      if(W.y*flip<0.||(H<scan&&H>back)) discard;
      vec3 alb=color; float metal=mr.x, rough=mr.y, shine=.12;
      if(has.x>0){ vec3 b=texture(tBase,U).rgb; alb*=b; shine=dot(b,vec3(.33)); }
      if(has.y>0){ vec3 q=texture(tMR,U).rgb; rough*=q.g; metal*=q.b; }
      vec3 n=normalize(N), v=normalize(eye-W);
      if(dot(n,v)<0.) n=-n;
      if(has.z>0) n=bump(n,texture(tNorm,U).xyz*2.-1.);
      vec3 L=texture(tLight,V).rgb;
      float nv=max(dot(n,v),.001), e=clamp(rough,.08,1.), occ=clamp(dot(L,vec3(.33))*1.5,.2,1.), night=1.-inspect;
      vec3 f0=mix(vec3(.04),alb,metal), g=f0+(max(vec3(1.-e),f0)-f0)*pow(1.-nv,5.), r=reflect(-v,n), body=f0*metal+alb*(1.-metal);
      vec3 key=normalize(vec3(-.4,1.,.55));
      vec3 c=(alb*(1.-metal)*L*1.12+f0*metal*L*(.5+.55*(1.-e)))*mix(1.,.2,night);  // the baked light is a studio: out on the ice it is night
      c+=g*mix(env(r,e)*1.8,studio(r,e),inspect)*(.6+.9*(1.-e))*occ;
      c+=g*lobe(n,v,key,e)*2.6*occ*mix(1.,.35,night);
      vec3 toCore=vec3(0.,.22,0.)-W; float far=length(toCore); vec3 lc=toCore/far;       // out there the core is the lamp
      vec3 lamp=vec3(1.,.86,.66)*(.12+beam*2.1)/(1.+far*far*1.5);
      c+=body*(lamp*(max(dot(n,lc),0.)*.9+lobe(n,v,lc,max(e,.3))*1.6)+vec3(.15,.2,.34)*(.35+.65*max(n.y,0.))*.55)*occ*night;
      c+=g*pow(max(dot(r,normalize(vec3(0.,.55,0.)-W)),0.),18.)*(beam*5.+.06)*night;
      if(has.w>0){ float pore=texture(tEmit,U).r; c=mix(c*1.15,c*.3+mix(vec3(1.,.62,.24),tone,heat)*(.01+power*power*7.*(1.-.75*inspect)),pore); }
      c+=emit*(.12+shine*2.4);
      c+=((alb*(1.-metal)*.42+f0*.05)*sqrt(nv)+vec3(.3,.36,.5)*pow(1.-nv,3.)*.5)*inspect;
      c=mix(vec3(dot(c,vec3(.33))),c,live)*mix(.25,1.,live)*dim;
      c+=vec3(.55,.5,1.)*hot*(.012+pow(1.-nv,2.)*.65);
      if(scan>-.5){ float b1=(H-scan)/.0014; c+=vec3(.35,1.,.85)*exp(-b1*b1)*10.; }
      if(back>-.5){ float b2=(H-back)/.0014; c+=vec3(.35,1.,.85)*exp(-b2*b2)*10.; }
      o=vec4(c,1.);
    }`, ['p', 'n', 'uv', 'uv2']);
  /* below the scan front the housing is only its own edges */
  const xrayP = compile(MODEL_VS,
    `in vec3 W; in vec3 N; in vec2 U; in float H; out vec4 o; uniform vec3 eye; uniform float flip, scan, back, dim, t; uniform int foam; uniform sampler2D tEmit;
    void main(){
      if(W.y*flip<0.||H>scan||H<back) discard;
      vec3 n=normalize(N), v=normalize(eye-W);
      float f=pow(1.-abs(dot(n,v)),2.2), lines=.8+.2*sin(W.y*880.+t*2.);
      float pores=foam>0?texture(tEmit,U).r*.14:0.;
      vec3 c=mix(vec3(.16,.62,1.),vec3(.5,.3,1.),f)*(f*1.05+.03+pores)*lines;
      float b=(H-scan)/.0016, b2=(H-back)/.0016;
      o=vec4((c+vec3(.35,1.,.85)*(exp(-b*b)+exp(-b2*b2))*6.)*dim,0.);
    }`, ['p', 'n', 'uv', 'uv2']);
  /* the dashed lines of the open Spark: where each part came from */
  const guideP = compile(`in vec4 p; uniform mat4 vp; uniform vec3 at; uniform float yaw, flip, scale; out float A;
      void main(){ A=p.w; vec3 o=p.xyz*scale; float c=cos(yaw), s=sin(yaw); vec3 q=vec3(c*o.x+s*o.z,o.y,-s*o.x+c*o.z)+at; q.y*=flip; gl_Position=vp*vec4(q,1.); }`,
    `in float A; out vec4 o; uniform float fade, t; void main(){ float d=step(.5,fract(A*90.-t*.7)); o=vec4(vec3(.45,.75,1.)*fade*(.25+.75*d),0.); }`, ['p']);

  /* the beam: a hair of light with beads racing up it, two filaments wound around it, a sheath of plasma, and one ring
     per draft position at its foot, as bright as the share of drafts that survive there */
  const beamP = compile(`in vec2 c; uniform mat4 vp; uniform vec3 right; uniform float flip; out vec2 U;
      void main(){ U=c; vec3 q=right*c.x*.25+vec3(0.,c.y*2.6,0.); q.y*=flip; gl_Position=vp*vec4(q,1.); }`,
    `in vec2 U; out vec4 o; uniform float t, beam, flash, num, rate, tilt, flip; uniform float spec[16]; uniform int specN; ${NOISE}
    void main(){
      float x=U.x*.25, y=U.y*2.6;                               // world units: out from the axis, up from the ice
      float up=t*(.7+rate*2.4);
      float fall=(1.-smoothstep(1.,1.52,y))*smoothstep(0.,.02,y);
      if(flip<0.) fall*=.55*(1.-smoothstep(.08,.62,y));         // in the ice only its foot: the whole length would run down across the page
      float hush=1.-num*smoothstep(.36,.43,y)*(1.-smoothstep(.87,.95,y));   // the speed floats in the beam and stays readable
      float sway=(noise(vec2(y*13.-up*4.,t*1.7))-.5)*.0022, cx=x-sway;
      float core=exp(-cx*cx*2.2e5)*9.+exp(-cx*cx*2.2e4)*2.4+exp(-cx*cx*3.5e3)*.55;
      float bead=pow(.5+.5*sin((y*8.5-up*3.1)*6.28318),8.)+.55*pow(.5+.5*sin((y*3.4-up*1.9)*6.28318+1.7),12.);
      float ph=y*23.-up*7.5, amp=(.03-.014*smoothstep(0.,1.2,y))*smoothstep(0.,.07,y);
      float a1=x-sin(ph)*amp, a2=x+sin(ph)*amp;
      float coil=exp(-a1*a1*6e4)*(.55+.45*cos(ph))+exp(-a2*a2*6e4)*(.55-.45*cos(ph));
      float n=fbm(vec2(x*30.,y*3.6-up*1.5)), n2=fbm(vec2(x*84.+3.,y*10.-up*2.9));
      float sheath=exp(-x*x*1100.)*(.5+1.5*n)+exp(-x*x*150.)*.11*n2;
      vec3 hot=vec3(.86,.97,1.), cyan=vec3(.28,.93,1.), violet=vec3(.5,.36,1.);
      vec3 c=hot*core*(1.+1.4*bead)*mix(.12,1.,hush)+mix(cyan,hot,.35)*coil*2.2*(.55+.45*bead)*hush+mix(violet,cyan,n)*sheath*hush;
      float rings=0., gap=.2/float(max(specN,4));                // the hoops climb the beam above the speed, where the sky is dark
      for(int i=0;i<16;i++){
        if(i>=specN||flip<0.) break;
        float R=.052-.0009*float(i), h=1.115+gap*float(i);
        vec2 e=vec2(x/R,(y-h)/(R*tilt));
        float len=length(e), d=(len-1.)*max(len,1e-4)/max(length(vec2(e.x/R,e.y/(R*tilt))),1e-4);  // distance to the oval, the same width all the way round
        rings+=spec[i]*exp(-d*d*9e4)*smoothstep(.25,-.3,e.y);   // only the near half of each hoop: sixteen full ovals would tangle
      }
      c+=hot*(exp(-(x*x*9e3+y*y*5200.))*8.+exp(-(x*x*900.+y*y*640.))*1.2);   // where it meets the ice
      o=vec4((c*fall+mix(cyan,hot,.35)*rings*2.4)*(beam*(1.+.05*sin(t*37.)+.04*sin(t*23.3))+flash*1.8),0.);
    }`, ['c']);

  /* the speed as digits of light, standing in the world above the core */
  const holoP = compile(`in vec4 a; uniform mat4 vp; uniform vec3 right, org; uniform float flip; out vec2 uv; out vec2 L;
      void main(){ uv=a.zw; L=a.xy; vec3 q=org+right*a.x+vec3(0.,a.y,0.); q.y*=flip; gl_Position=vp*vec4(q,1.); }`,
    `in vec2 uv; in vec2 L; out vec4 o; uniform sampler2D tex; uniform float t, fade, light;
    void main(){
      if(light<.5){ o=vec4(0.,0.,0.,clamp(texture(tex,uv,4.5).a*1.9,0.,.78)*fade); return; }
      float a=texture(tex,uv).a, scan=.92+.08*sin(gl_FragCoord.y*1.6+t*5.);
      o=vec4(mix(vec3(.66,.6,1.),vec3(1.),smoothstep(-.6,.6,L.y/.23))*1.9*a*scan*fade,0.);
    }`, ['a']);

  /* one streak per token: a capsule from where it was to where it is, with a hot head */
  const fireP = compile(`in vec2 c; in vec4 p; in vec4 q; in vec4 k; uniform mat4 vp; uniform vec2 res; uniform float flip, sc; out vec2 U; out vec4 C; out float H;
      void main(){
        vec4 a=vp*vec4(p.x,p.y*flip,p.z,1.);
        vec3 tail=p.xyz-q.xyz*q.w;
        vec4 b=vp*vec4(tail.x,tail.y*flip,tail.z,1.);
        vec2 sa=a.xy/a.w*res*.5, sb=b.xy/b.w*res*.5, dir=sa-sb;
        float len=length(dir); dir=len>.001?dir/len:vec2(1.,0.);
        float w=clamp(p.w*sc/a.w,.8,6.); H=len*.5/w;
        U=vec2(c.x*(H+1.),c.y); C=k;
        vec2 px=(sa+sb)*.5+dir*c.x*(len*.5+w)+vec2(-dir.y,dir.x)*c.y*w;
        gl_Position=vec4(px/res*2.,a.z/a.w,1.);
      }`,
    `in vec2 U; in vec4 C; in float H; out vec4 o;
    void main(){
      float along=clamp((U.x+H)/(2.*H+1e-3),0.,1.);            // 0 at the tail, 1 at the head
      float thin=mix(.2,1.,along*along);                         // the tail thins out to a hair
      float x=max(abs(U.x)-H,0.), y=U.y/thin, d=sqrt(x*x+y*y);
      float core=exp(-d*d*7.5), halo=exp(-d*d*1.9)*(1.-smoothstep(.72,1.,d));
      float lum=(halo*.3+core*1.3)*(.05+along*along*along*1.55);
      vec3 white=vec3(1.,.97,.9)*max(C.r,max(C.g,C.b));         // white-hot in the middle of the head, its own colour around it
      o=vec4(mix(C.rgb,white,core*along*.85)*C.a*lum,0.);
    }`, ['c', 'p', 'q', 'k']);

  /* what is bright enough to glow: only what lies above white is kept */
  const brightP = compile(FULL, `in vec2 v; out vec4 o; uniform sampler2D tex;
    void main(){ vec3 c=min(texture(tex,v).rgb,vec3(40.)); float l=max(c.r,max(c.g,c.b)); o=vec4(c*smoothstep(1.,2.2,l),1.); }`, ['p']);
  /* one step down the glow pyramid: half the size, blurred */
  const downP = compile(FULL, `in vec2 v; out vec4 o; uniform sampler2D tex; uniform vec2 px;
    void main(){ o=(texture(tex,v)*4.+texture(tex,v-px)+texture(tex,v+px)+texture(tex,v+vec2(px.x,-px.y))+texture(tex,v-vec2(px.x,-px.y)))/8.; }`, ['p']);
  /* one step back up the glow pyramid: blurred wider and added on */
  const upP = compile(FULL, `in vec2 v; out vec4 o; uniform sampler2D tex; uniform vec2 px;
    void main(){ vec2 a=px*2.;
      o=(texture(tex,v+vec2(-a.x,0.))+texture(tex,v+vec2(-px.x,px.y))*2.+texture(tex,v+vec2(0.,a.y))+texture(tex,v+px)*2.+texture(tex,v+vec2(a.x,0.))+texture(tex,v+vec2(px.x,-px.y))*2.+texture(tex,v+vec2(0.,-a.y))+texture(tex,v-px)*2.)/12.; }`, ['p']);
  /* the picture on the screen: scene plus glow, a little colour fringe and vignette, tone mapped, with film grain.
     pane is the hole the scene shows through, in pixels from the bottom left; outside it the picture is dimmed by veil.x, over an edge veil.y wide */
  const finalP = compile(FULL, `in vec2 v; out vec4 o; uniform sampler2D scene, glow; uniform float t, grain; uniform vec4 pane; uniform vec2 veil;
    float h(vec2 p){ return fract(sin(dot(p,vec2(12.9898,78.233))+t)*43758.5453); }
    void main(){
      vec2 d=v-.5; float r2=dot(d,d), ca=r2*.0065;
      vec3 c=vec3(texture(scene,v-d*ca).r,texture(scene,v).g,texture(scene,v+d*ca).b);
      c+=texture(glow,v).rgb*.11;
      c*=1.-smoothstep(.16,.62,r2)*.5;
      vec2 e=min(gl_FragCoord.xy-pane.xy,pane.zw-gl_FragCoord.xy);
      c*=mix(1.-veil.x,1.,smoothstep(0.,veil.y,min(e.x,e.y)));
      c=clamp((c*(2.51*c+.03))/(c*(2.43*c+.59)+.14),0.,1.);
      c=pow(c,vec3(1./2.2));
      o=vec4(c+(h(gl_FragCoord.xy)-.5)*grain,1.);
    }`, ['p']);

  Object.assign(shared, { COLOR, TEXEL, beamP, brightP, copyP, downP, finalP, fireP, guideP, holoP, iceP, laneP, modelP, skyP, sparkP, starP, upP, xrayP });  // seam
}  // seam
