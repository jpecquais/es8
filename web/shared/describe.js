// Textes lisibles (en anglais) : valeurs de champs et modifications en attente.
// Les listes de libellés viennent de labels.py (via names()).

export function makeDescriber(N) {
  const loopName = (i) => N.loop_labels[N.loops[i]];
  const slotName = (i) => N.ctl_slot_labels[N.ctl_slots[i]];
  const division = (v) => N.tempo_divisions[v];

  /** Valeur d'un champ de patch (élément `i` pour un champ liste). */
  function value(field, v, fields, i) {
    if (["loop_sw", "carry_over_loop", "assign_sw", "ctl_min", "ctl_max"].includes(field) || /^led_/.test(field)) return v ? "On" : "Off";
    if (field === "ctl_func") return N.ctl_function_labels[v] ?? v;
    if (field === "assign_source") return N.assign_source_labels[v] ?? v;
    if (field === "assign_target") return N.assign_target_labels[v] ?? v;
    if ((field === "assign_target_min" || field === "assign_target_max") && fields) {
      const values = N.assign_target_values[fields.assign_target[i]];
      return values ? values[v] ?? v : v;
    }
    if (field === "assign_wave_pedal_rate") return v < 20 ? division(v) ?? v : String(v - 20);
    if (field === "name") return `"${String(v).trimEnd()}"`;
    if (field === "master_bpm") return `${v} BPM`;
    if (/^ctl\d$/.test(field)) return division(v) ? division(v) : v >= 20 ? `${v} BPM` : v ? "On" : "Off";
    const labels = N.patch_values[field] || N.system_values[field];
    return labels ? labels[v] ?? v : v;
  }

  const FIELD = {
    name: "Name", master_bpm: "Tempo", loop_position: "Chain order",
    input_select: "Input", input_buffer: "Input buffer", output_select: "Output",
    output_buffer: "Output buffer", output_gain: "Output gain", mixer_mode: "Mixer",
    mixer_gain1: "Mixer gain 1", mixer_gain2: "Mixer gain 2", midi_clock_out: "MIDI clock",
    exp1: "EXP 1 on patch call", exp2: "EXP 2 on patch call",
  };
  const ASSIGN = {
    assign_sw: "", assign_source: "source", assign_target: "target", assign_mode: "mode",
    assign_target_min: "off value", assign_target_max: "on value",
    assign_act_range_lo: "range low", assign_act_range_hi: "range high",
    assign_target_cc_ch: "CC channel", assign_target_cc_no: "CC number",
    assign_int_pedal_trigger: "pedal trigger", assign_int_pedal_trigger_cc: "trigger CC",
    assign_int_pedal_time: "pedal time", assign_int_pedal_curve: "pedal curve",
    assign_wave_pedal_rate: "wave rate", assign_wave_pedal_form: "wave form",
  };
  const MIDI = {
    midi_tx_ch: "channel", midi_pc: "PC", midi_pc_bank_msb: "bank MSB", midi_pc_bank_lsb: "bank LSB",
    midi_ctl1_cc: "CC 1", midi_ctl1_cc_val: "CC 1 value", midi_ctl2_cc: "CC 2", midi_ctl2_cc_val: "CC 2 value",
    midi_transmit: "send",
  };

  /** Libellé d'un champ (élément `i` pour un champ liste). */
  function label(field, i) {
    if (field === "loop_sw") return loopName(i);
    if (field === "carry_over_loop") return `Carry-over, ${loopName(i)}`;
    if (field === "ctl_func") return slotName(i);
    if (field === "ctl_mod") return `${slotName(i)}, mode`;
    if (field === "ctl_min" || field === "ctl_max") return `${slotName(i)}, ${field.slice(4)}`;
    if (field === "exp_func") return `EXP ${i + 1}`;
    if (field === "exp_min" || field === "exp_max") return `EXP ${i + 1}, ${field.slice(4)}`;
    if (field in ASSIGN) return `Assign ${i + 1}${ASSIGN[field] ? `, ${ASSIGN[field]}` : ""}`;
    if (field.startsWith("assign_")) return `Assign ${i + 1}, ${field.slice(7).replaceAll("_", " ")}`;
    if (field in MIDI) return `MIDI ${i + 1}, ${MIDI[field]}`;
    if (/^led_/.test(field)) return `LED ${field.slice(4).replace("num", "Number ").replace("bank_d", "Bank ▼").replace("bank_u", "Bank ▲")}`;
    if (/^ctl\d$/.test(field)) return `CTL ${field[3]} on patch call`;
    if (i !== undefined) return `${FIELD[field] || field} ${i + 1}`;
    return FIELD[field] || field;
  }

  /** Une modification du résumé → lignes { field, index, what, from, to }. */
  function lines(change, fields) {
    const { field, old, new: now } = change;
    if (change.chain) return [{ field, index: null, what: "Chain order", from: old, to: now }];
    if (Array.isArray(old)) {
      const out = [];
      old.forEach((v, i) => {
        if (v === now[i]) return;
        if (field === "assign_sw") {
          out.push({ field, index: i, what: `Assign ${i + 1}`, from: v ? "active" : "off", to: now[i] ? "active" : "off" });
        } else {
          out.push({ field, index: i, what: label(field, i), from: value(field, v, fields, i), to: value(field, now[i], fields, i) });
        }
      });
      return out;
    }
    return [{ field, index: null, what: label(field), from: value(field, old, fields), to: value(field, now, fields) }];
  }

  /** Réglage système → texte. */
  function systemValue(field, v) {
    if (Array.isArray(v)) return `${v.length} values`;
    const labels = N.system_values[field];
    return labels ? labels[v] ?? v : v;
  }

  return { value, label, lines, systemValue, loopName, slotName, division };
}
