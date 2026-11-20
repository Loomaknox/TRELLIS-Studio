import {t} from './i18n.js';

// Keep browser validation in the application's language, regardless of OS locale.
document.addEventListener('invalid',event=>{
 const input=event.target;if(!('validity' in input))return;
 const state=input.validity;let message=t('Please check this value.');
 if(state.valueMissing)message=t(input.type==='file'?'Choose a file.':'Please fill in this field.');
 else if(state.rangeUnderflow)message=t('Enter a value of at least {minimum}.',{minimum:input.min});
 else if(state.rangeOverflow)message=t('Enter a value no greater than {maximum}.',{maximum:input.max});
 else if(state.stepMismatch)message=t('Choose a value using increments of {step}.',{step:input.step});
 else if(state.badInput)message=t('Enter a valid number.');
 else if(state.tooLong)message=t('Use no more than {maximum} characters.',{maximum:input.maxLength});
 input.setCustomValidity(message);
},true);
document.addEventListener('input',event=>event.target.setCustomValidity?.(''),true);
