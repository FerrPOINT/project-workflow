export function isHex(value) { return typeof value === "string" && /^#[a-f\d]{6}$/i.test(value); }
function luminance(color) {
 return [1,3,5].map(i=>parseInt(color.slice(i,i+2),16)/255).map(v=>v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[0.2126,0.7152,0.0722][i],0);
}
export function contrast(a,b) {
 if (!isHex(a) || !isHex(b)) return 0;
 const first=luminance(a),second=luminance(b);return (Math.max(first,second)+0.05)/(Math.min(first,second)+0.05);
}
export function foreground(color) { return contrast(color,"#000000") >= contrast(color,"#ffffff") ? "#000000" : "#ffffff"; }
