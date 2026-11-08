export const API=import.meta.env.VITE_API_URL||import.meta.env.VITE_API_BASE_URL||'http://127.0.0.1:38081';
export async function request(path:string,init?:RequestInit){const r=await fetch(API+path,{headers:{'Content-Type':'application/json'},...init});if(!r.ok)throw new Error((await r.text()).slice(0,300));return r.json()}
