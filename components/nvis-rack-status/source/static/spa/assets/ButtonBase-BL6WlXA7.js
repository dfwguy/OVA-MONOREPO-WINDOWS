import{i as e}from"./rolldown-runtime-COiEfhsA.js";import{B as t,R as n,c as r,k as i,l as a,u as o}from"./createTheme-BiNRG8NI.js";import{r as s}from"./emotion-react.browser.esm-Bu4tgvwC.js";import{n as c,r as l,s as u}from"./memoTheme-BvU_Zcp_.js";import{a as d,i as f,n as p,r as m}from"./useEventCallback-D-VvAOf4.js";import{i as h,n as g,r as _}from"./useTimeout-CB5W7lMA.js";import{t as v}from"./isFocusVisible-CmHL3Ev5.js";function y(e){if(e===void 0)throw ReferenceError(`this hasn't been initialised - super() hasn't been called`);return e}var b=e(t());function x(e,t){var n=function(e){return t&&(0,b.isValidElement)(e)?t(e):e},r=Object.create(null);return e&&b.Children.map(e,function(e){return e}).forEach(function(e){r[e.key]=n(e)}),r}function S(e,t){e||={},t||={};function n(n){return n in t?t[n]:e[n]}var r=Object.create(null),i=[];for(var a in e)a in t?i.length&&(r[a]=i,i=[]):i.push(a);var o,s={};for(var c in t){if(r[c])for(o=0;o<r[c].length;o++){var l=r[c][o];s[r[c][o]]=n(l)}s[c]=n(c)}for(o=0;o<i.length;o++)s[i[o]]=n(i[o]);return s}function C(e,t,n){return n[t]==null?e.props[t]:n[t]}function w(e,t){return x(e.children,function(n){return(0,b.cloneElement)(n,{onExited:t.bind(null,n),in:!0,appear:C(n,`appear`,e),enter:C(n,`enter`,e),exit:C(n,`exit`,e)})})}function T(e,t,n){var r=x(e.children),i=S(t,r);return Object.keys(i).forEach(function(a){var o=i[a];if((0,b.isValidElement)(o)){var s=a in t,c=a in r,l=t[a],u=(0,b.isValidElement)(l)&&!l.props.in;c&&(!s||u)?i[a]=(0,b.cloneElement)(o,{onExited:n.bind(null,o),in:!0,exit:C(o,`exit`,e),enter:C(o,`enter`,e)}):!c&&s&&!u?i[a]=(0,b.cloneElement)(o,{in:!1}):c&&s&&(0,b.isValidElement)(l)&&(i[a]=(0,b.cloneElement)(o,{onExited:n.bind(null,o),in:l.props.in,exit:C(o,`exit`,e),enter:C(o,`enter`,e)}))}}),i}var E=Object.values||function(e){return Object.keys(e).map(function(t){return e[t]})},D={component:`div`,childFactory:function(e){return e}},O=function(e){f(t,e);function t(t,n){var r=e.call(this,t,n)||this;return r.state={contextValue:{isMounting:!0},handleExited:r.handleExited.bind(y(r)),firstRender:!0},r}var r=t.prototype;return r.componentDidMount=function(){this.mounted=!0,this.setState({contextValue:{isMounting:!1}})},r.componentWillUnmount=function(){this.mounted=!1},t.getDerivedStateFromProps=function(e,t){var n=t.children,r=t.handleExited;return{children:t.firstRender?w(e,r):T(e,n,r),firstRender:!1}},r.handleExited=function(e,t){var r=x(this.props.children);e.key in r||(e.props.onExited&&e.props.onExited(t),this.mounted&&this.setState(function(t){var r=n({},t.children);return delete r[e.key],{children:r}}))},r.render=function(){var e=this.props,t=e.component,n=e.childFactory,r=d(e,[`component`,`childFactory`]),i=this.state.contextValue,a=E(this.state.children).map(n);return delete r.appear,delete r.enter,delete r.exit,t===null?b.createElement(m.Provider,{value:i},a):b.createElement(m.Provider,{value:i},b.createElement(t,r,a))},t}(b.Component);O.propTypes={},O.defaultProps=D;function k(e){let{focusableWhenDisabled:t,disabled:n,composite:r=!1,tabIndex:i=0,isNativeButton:a}=e,o=r&&t!==!1,s=r&&t===!1;return b.useMemo(()=>{let e={onKeyDown(e){n&&t&&e.key!==`Tab`&&e.preventDefault()}};return r||(e.tabIndex=i,!a&&n&&(e.tabIndex=t?i:-1)),(a&&(t||o)||!a&&n)&&(e[`aria-disabled`]=n),a&&(!t||s)&&(e.disabled=n),e},[r,n,t,o,s,a,i])}var A={};function ee(e){let{nativeButton:t,nativeButtonProp:n,internalNativeButton:r=t,allowInferredHostMismatch:i=!1,disabled:a,type:o,hasFormAction:s=!1,tabIndex:c=0,focusableWhenDisabled:l,stopEventPropagation:u=!1,onBeforeKeyDown:d,onBeforeKeyUp:f}=e,p=b.useRef(null),m=l===!0,h=k({focusableWhenDisabled:m,disabled:a,isNativeButton:t,tabIndex:c}),g=b.useCallback(()=>{let e=p.current;return e==null?t:e.tagName===`BUTTON`||!!(e.tagName===`A`&&e.href)},[t]),_=b.useMemo(()=>{let e=m?{}:{tabIndex:a?-1:c};return t?(e.type=o===void 0&&!s?`button`:o,m||(e.disabled=a)):(e.role=`button`,!m&&a&&(e[`aria-disabled`]=a)),m?{...e,...h}:e},[a,m,h,s,t,c,o]);return{getButtonProps:b.useCallback((e=A)=>{let{onClick:t,onKeyDown:n,onKeyUp:r,...i}=e,o=e=>{u&&e.stopPropagation(),a?e.preventDefault():t?.(e)},s=e=>{m&&h.onKeyDown(e),!a&&(d?.(e),n?.(e),!(e.target!==e.currentTarget||g())&&(e.key===` `?e.preventDefault():e.key===`Enter`&&(e.preventDefault(),e.currentTarget.click())))},c=e=>{a||(f?.(e),r?.(e),e.target===e.currentTarget&&!g()&&e.key===` `&&!e.defaultPrevented&&e.currentTarget.click())};return{..._,...i,onClick:o,onKeyDown:s,onKeyUp:c}},[_,a,m,h,g,d,f,u]),rootRef:p}}var j=class e{static create(){return new e}static use(){let t=_(e.create).current,[n,r]=b.useState(!1);return t.shouldMount=n,t.setShouldMount=r,b.useEffect(t.mountEffect,[n]),t}constructor(){this.ref={current:null},this.mounted=null,this.didMount=!1,this.shouldMount=!1,this.setShouldMount=null}mount(){return this.mounted||(this.mounted=M(),this.shouldMount=!0,this.setShouldMount(this.shouldMount)),this.mounted}mountEffect=()=>{this.shouldMount&&!this.didMount&&this.ref.current!==null&&(this.didMount=!0,this.mounted.resolve())};start(...e){this.mount().then(()=>this.ref.current?.start(...e))}stop(...e){this.mount().then(()=>this.ref.current?.stop(...e))}pulsate(...e){this.mount().then(()=>this.ref.current?.pulsate(...e))}};function te(){return j.use()}function M(){let e,t,n=new Promise((n,r)=>{e=n,t=r});return n.resolve=e,n.reject=t,n}var N=i();function P(e){let{className:t,classes:n,pulsate:r=!1,rippleX:i,rippleY:a,rippleSize:s,in:c,onExited:l,timeout:u}=e,[d,f]=b.useState(!1),p=o(t,n.ripple,n.rippleVisible,r&&n.ripplePulsate),m={width:s,height:s,top:-(s/2)+a,left:-(s/2)+i},h=o(n.child,d&&n.childLeaving,r&&n.childPulsate);return!c&&!d&&f(!0),b.useEffect(()=>{if(!c&&l!=null){let e=setTimeout(l,u);return()=>{clearTimeout(e)}}},[l,c,u]),(0,N.jsx)(`span`,{className:p,style:m,children:(0,N.jsx)(`span`,{className:h})})}var F=r(`MuiTouchRipple`,[`root`,`ripple`,`rippleVisible`,`ripplePulsate`,`child`,`childLeaving`,`childPulsate`]),I=550,L=s`
  0% {
    transform: scale(0);
    opacity: 0.1;
  }

  100% {
    transform: scale(1);
    opacity: 0.3;
  }
`,R=s`
  0% {
    opacity: 1;
  }

  100% {
    opacity: 0;
  }
`,z=s`
  0% {
    transform: scale(1);
  }

  50% {
    transform: scale(0.92);
  }

  100% {
    transform: scale(1);
  }
`,B=l(`span`,{name:`MuiTouchRipple`,slot:`Root`})({overflow:`hidden`,pointerEvents:`none`,position:`absolute`,zIndex:0,top:0,right:0,bottom:0,left:0,borderRadius:`inherit`}),V=l(P,{name:`MuiTouchRipple`,slot:`Ripple`})`
  opacity: 0;
  position: absolute;

  &.${F.rippleVisible} {
    opacity: 0.3;
    transform: scale(1);
    animation-name: ${L};
    animation-duration: ${I}ms;
    animation-timing-function: ${({theme:e})=>e.transitions.easing.easeInOut};
  }

  &.${F.ripplePulsate} {
    animation-duration: ${({theme:e})=>e.transitions.duration.shorter}ms;
  }

  & .${F.child} {
    opacity: 1;
    display: block;
    width: 100%;
    height: 100%;
    border-radius: 50%;
    background-color: currentColor;
  }

  & .${F.childLeaving} {
    opacity: 0;
    animation-name: ${R};
    animation-duration: ${I}ms;
    animation-timing-function: ${({theme:e})=>e.transitions.easing.easeInOut};
  }

  & .${F.childPulsate} {
    position: absolute;
    /* @noflip */
    left: 0px;
    top: 0;
    animation-name: ${z};
    animation-duration: 2500ms;
    animation-timing-function: ${({theme:e})=>e.transitions.easing.easeInOut};
    animation-iteration-count: infinite;
    animation-delay: 200ms;
  }
`,ne=b.forwardRef(function(e,t){let{center:n=!1,classes:r={},className:i,...a}=c({props:e,name:`MuiTouchRipple`}),[s,l]=b.useState([]),u=b.useRef(0),d=b.useRef(null);b.useEffect(()=>{d.current&&=(d.current(),null)},[s]);let f=b.useRef(!1),p=g(),m=b.useRef(null),h=b.useRef(null),_=b.useCallback(e=>{let{pulsate:t,rippleX:n,rippleY:i,rippleSize:a,cb:s}=e;l(e=>[...e,(0,N.jsx)(V,{classes:{ripple:o(r.ripple,F.ripple),rippleVisible:o(r.rippleVisible,F.rippleVisible),ripplePulsate:o(r.ripplePulsate,F.ripplePulsate),child:o(r.child,F.child),childLeaving:o(r.childLeaving,F.childLeaving),childPulsate:o(r.childPulsate,F.childPulsate)},timeout:I,pulsate:t,rippleX:n,rippleY:i,rippleSize:a},u.current)]),u.current+=1,d.current=s},[r]),v=b.useCallback((e={},t={},r=()=>{})=>{let{pulsate:i=!1,center:a=n||t.pulsate,fakeElement:o=!1}=t;if(e?.type===`mousedown`&&f.current){f.current=!1;return}e?.type===`touchstart`&&(f.current=!0);let s=o?null:h.current,c=s?s.getBoundingClientRect():{width:0,height:0,left:0,top:0},l,u,d;if(a||e===void 0||e.clientX===0&&e.clientY===0||!e.clientX&&!e.touches)l=Math.round(c.width/2),u=Math.round(c.height/2);else{let{clientX:t,clientY:n}=e.touches&&e.touches.length>0?e.touches[0]:e;l=Math.round(t-c.left),u=Math.round(n-c.top)}if(a)d=Math.sqrt((2*c.width**2+c.height**2)/3),d%2==0&&(d+=1);else{let e=Math.max(Math.abs((s?s.clientWidth:0)-l),l)*2+2,t=Math.max(Math.abs((s?s.clientHeight:0)-u),u)*2+2;d=Math.sqrt(e**2+t**2)}e?.touches?m.current===null&&(m.current=()=>{_({pulsate:i,rippleX:l,rippleY:u,rippleSize:d,cb:r})},p.start(80,()=>{m.current&&=(m.current(),null)})):_({pulsate:i,rippleX:l,rippleY:u,rippleSize:d,cb:r})},[n,_,p]),y=b.useCallback(()=>{v({},{pulsate:!0})},[v]),x=b.useCallback((e,t)=>{p.clear(),e?.type===`touchend`&&m.current?(m.current(),m.current=null,p.start(0,()=>{x(e,t)})):(m.current=null,l(e=>e.length>0?e.slice(1):e),d.current=t)},[p]);return b.useImperativeHandle(t,()=>({pulsate:y,start:v,stop:x}),[y,v,x]),(0,N.jsx)(B,{className:o(F.root,r.root,i),ref:h,...a,children:(0,N.jsx)(O,{component:null,exit:!0,children:s})})});function H(e){return a(`MuiButtonBase`,e)}var U=r(`MuiButtonBase`,[`root`,`disabled`,`focusVisible`]),re=e=>{let{disabled:t,focusVisible:n,focusVisibleClassName:r,suppressFocusVisible:i,classes:a}=e,o=u({root:[`root`,t&&`disabled`,n&&!i&&`focusVisible`]},H,a);return n&&!i&&r&&(o.root+=` ${r}`),o},ie=l(`button`,{name:`MuiButtonBase`,slot:`Root`})({display:`inline-flex`,alignItems:`center`,justifyContent:`center`,position:`relative`,boxSizing:`border-box`,WebkitTapHighlightColor:`transparent`,backgroundColor:`transparent`,outline:0,border:0,margin:0,borderRadius:0,padding:0,cursor:`pointer`,userSelect:`none`,verticalAlign:`middle`,MozAppearance:`none`,WebkitAppearance:`none`,textDecoration:`none`,color:`inherit`,"&::-moz-focus-inner":{borderStyle:`none`},[`&.${U.disabled}`]:{pointerEvents:`none`,cursor:`default`},"@media print":{colorAdjust:`exact`}}),W=b.forwardRef(function(e,t){let n=c({props:e,name:`MuiButtonBase`}),{action:r,centerRipple:i=!1,children:a,className:s,component:l=`button`,disabled:u=!1,disableRipple:d=!1,disableTouchRipple:f=!1,focusRipple:m=!1,focusVisibleClassName:g,focusableWhenDisabled:_,suppressFocusVisible:y=!1,internalNativeButton:x,LinkComponent:S=`a`,nativeButton:C,onBlur:w,onClick:T,onContextMenu:E,onDragLeave:D,onFocus:O,onFocusVisible:k,onKeyDown:A,onKeyUp:j,onMouseDown:M,onMouseLeave:P,onMouseUp:F,onTouchEnd:I,onTouchMove:L,onTouchStart:R,tabIndex:z=0,TouchRippleProps:B,touchRippleRef:V,type:H,...U}=n,W=!!(U.href||U.to),ae=!!U.formAction,K=l;K===`button`&&W&&(K=S);let q=typeof K==`string`?K===`button`:x??!1,oe=C??q,J=te(),se=p(J.ref,V),[Y,X]=b.useState(!1);(u||y)&&Y&&X(!1);let ce=h(e=>{m&&!e.repeat&&Y&&e.key===` `&&J.stop(e,()=>{J.start(e)})}),le=h(e=>{m&&e.key===` `&&Y&&!e.defaultPrevented&&J.stop(e,()=>{J.pulsate(e)})}),{getButtonProps:ue,rootRef:Z}=ee({nativeButton:oe,nativeButtonProp:C,internalNativeButton:q,allowInferredHostMismatch:W||typeof K==`string`,disabled:u,type:H,hasFormAction:ae,tabIndex:z,onBeforeKeyDown:ce,onBeforeKeyUp:le}),{onClick:de,onKeyDown:fe,onKeyUp:pe,...me}=ue({onClick:T,onKeyDown:A,onKeyUp:j});b.useImperativeHandle(r,()=>({focusVisible:()=>{X(!0),Z.current.focus()}}),[Z]);let he=J.shouldMount&&!d&&!u;b.useEffect(()=>{Y&&m&&!d&&J.pulsate()},[d,m,Y,J]);let ge=G(J,`start`,M,f),_e=G(J,`stop`,E,f),ve=G(J,`stop`,D,f),ye=G(J,`stop`,F,f),be=G(J,`stop`,e=>{Y&&e.preventDefault(),P&&P(e)},f),xe=G(J,`start`,R,f),Se=G(J,`stop`,I,f),Ce=G(J,`stop`,L,f),we=G(J,`stop`,e=>{v(e.target)||X(!1),w&&w(e)},!1),Te=h(e=>{Z.current||=e.currentTarget,!y&&v(e.target)&&(X(!0),k&&k(e)),O&&O(e)}),Q={};W&&(Q.tabIndex=u?-1:z,u&&(Q[`aria-disabled`]=u),Q.type=H);let Ee=p(t,Z),$={...n,centerRipple:i,component:l,disabled:u,disableRipple:d,disableTouchRipple:f,focusRipple:m,suppressFocusVisible:y,tabIndex:z,focusVisible:Y},De=re($);return(0,N.jsxs)(ie,{as:K,className:o(De.root,s),ownerState:$,onBlur:we,onClick:de,onContextMenu:_e,onFocus:Te,onKeyDown:fe,onKeyUp:pe,onMouseDown:ge,onMouseLeave:be,onMouseUp:ye,onDragLeave:ve,onTouchEnd:Se,onTouchMove:Ce,onTouchStart:xe,ref:Ee,...W?Q:me,...U,children:[a,he?(0,N.jsx)(ne,{ref:se,center:i,...B}):null]})});function G(e,t,n,r=!1){return h(i=>(n&&n(i),r||e[t](i),!0))}export{W as t};