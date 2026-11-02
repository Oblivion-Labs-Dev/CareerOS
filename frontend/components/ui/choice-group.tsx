"use client";
import {useId} from "react";
import styles from "./choice-group.module.css";
export type Choice = {value: string; label: string};
export function ChoiceGroup({label,options,value,onChange,multiple=false}: {label:string; options:Choice[];value:string[];onChange:(value:string[])=>void;multiple?:boolean}) {
  const name=useId();
  return <fieldset className={styles.group} aria-label={label}><legend>{label}{multiple && <small>Choose any</small>}</legend><div>{options.map(option=><label key={option.value} className={styles.option}><input type={multiple ? "checkbox" : "radio"} name={name} value={option.value} checked={value.includes(option.value)} onChange={()=>onChange(multiple ? value.includes(option.value) ? value.filter(v=>v!==option.value) : [...value,option.value] : [option.value])}/><span>{multiple && <i aria-hidden="true">{value.includes(option.value) ? "✓" : "+"}</i>}{option.label}</span></label>)}</div></fieldset>;
}
