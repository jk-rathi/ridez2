import { useId, useRef, useState } from 'react';

export default function OtpInput({onChange, disabled}) {
  const [digits,setDigits]=useState(Array(6).fill(''));
  const inputs=useRef([]);
  const id=useId();
  function update(index,value) {
    const numbers=value.replace(/[^0-9]/g,'');
    if(value && !numbers)return;
    const next=[...digits];
    if(!numbers)next[index]='';
    else numbers.slice(0,6-index).split('').forEach((digit,offset)=>{next[index+offset]=digit;});
    setDigits(next);
    onChange(next.join(''));
    if(numbers)inputs.current[Math.min(index+numbers.length,5)]?.focus();
  }
  return <fieldset className="otp-entry" disabled={disabled}>
    <legend>Verify rider OTP</legend>
    <p id={`${id}-hint`}>Ask the rider for their six-digit code before starting.</p>
    <div className="otp-blocks" role="group" aria-label="Rider OTP" aria-describedby={`${id}-hint`}>
      {digits.map((digit,index)=><input key={index} ref={element=>{inputs.current[index]=element;}} aria-label={`OTP digit ${index+1} of 6`} type="text" inputMode="numeric" autoComplete="off" value={digit} className={digit?'is-filled':''} onFocus={event=>event.target.select()} onChange={event=>update(index,event.target.value)} onPaste={event=>{event.preventDefault();update(index,event.clipboardData.getData('text'));}} onKeyDown={event=>{
        if(event.key==='Backspace') {
          event.preventDefault();
          const target=digits[index]?index:Math.max(0,index-1);
          update(target,'');inputs.current[target]?.focus();
        } else if(event.key==='ArrowLeft' || event.key==='ArrowRight') {
          event.preventDefault();inputs.current[Math.max(0,Math.min(5,index+(event.key==='ArrowLeft'?-1:1)))]?.focus();
        } else if(event.key==='Home' || event.key==='End') {
          event.preventDefault();inputs.current[event.key==='Home'?0:5]?.focus();
        }
      }}/>)}
    </div>
  </fieldset>;
}
