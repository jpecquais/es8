// Textes lisibles : valeurs de champs et modifications en attente.
// Les listes de libellés viennent de labels.py (via names()).

export function makeDescriber(N) {
  const loopName = (i) => N.loop_labels[N.loops[i]];
  const slotName = (i) => N.ctl_slot_labels[N.ctl_slots[i]];

  /** Valeur d'un champ de patch (élément `i` pour un champ liste). */
  function value(field, v, fields, i) {
    if (field === "loop_sw" || field === "carry_over_loop" || field === "assign_sw") return v ? "On" : "Off";
    if (field === "ctl_func") return N.ctl_function_labels[v] ?? v;
    if (field === "assign_source") return N.assign_source_labels[v] ?? v;
    if (field === "assign_target") return N.assign_target_labels[v] ?? v;
    if ((field === "assign_target_min" || field === "assign_target_max") && fields) {
      const values = N.assign_target_values[fields.assign_target[i]];
      return values ? values[v] ?? v : v;
    }
    if (field === "name") return `« ${String(v).trimEnd()} »`;
    if (field === "master_bpm") return `${v} BPM`;
    const labels = N.patch_values[field] || N.system_values[field];
    return labels ? labels[v] ?? v : v;
  }

  const FIELD = {
    name: "Nom", master_bpm: "Tempo", loop_position: "Ordre de la chaîne",
    input_select: "Entrée", input_buffer: "Buffer d'entrée", output_select: "Sortie",
    output_buffer: "Buffer de sortie", output_gain: "Gain de sortie", mixer_mode: "Mixer",
    mixer_gain1: "Mixer, gain 1", mixer_gain2: "Mixer, gain 2", midi_clock_out: "Horloge MIDI",
    midi_transmit: "Envoi MIDI", exp1: "EXP 1 à l'appel", exp2: "EXP 2 à l'appel",
  };
  const ASSIGN = {
    assign_sw: "", assign_source: "source", assign_target: "cible", assign_mode: "mode",
    assign_target_min: "valeur min", assign_target_max: "valeur max",
    assign_act_range_lo: "plage basse", assign_act_range_hi: "plage haute",
  };
  const MIDI = {
    midi_tx_ch: "canal", midi_pc: "PC", midi_pc_bank_msb: "banque MSB", midi_pc_bank_lsb: "banque LSB",
    midi_ctl1_cc: "CC 1", midi_ctl1_cc_val: "valeur CC 1", midi_ctl2_cc: "CC 2", midi_ctl2_cc_val: "valeur CC 2",
  };

  /** Libellé d'un champ (élément `i` pour un champ liste). */
  function label(field, i) {
    if (field === "loop_sw") return loopName(i);
    if (field === "carry_over_loop") return `Carry-over ${loopName(i)}`;
    if (field === "ctl_func") return slotName(i);
    if (field === "ctl_mod") return `${slotName(i)}, mode`;
    if (field === "ctl_min" || field === "ctl_max") return `${slotName(i)}, ${field.slice(4)}`;
    if (field in ASSIGN) return `Assign ${i + 1}${ASSIGN[field] ? `, ${ASSIGN[field]}` : ""}`;
    if (field.startsWith("assign_")) return `Assign ${i + 1}, ${field.slice(7).replaceAll("_", " ")}`;
    if (field in MIDI) return `MIDI ${i + 1}, ${MIDI[field]}`;
    if (/^led_/.test(field)) return `LED ${field.slice(4).replace("num", "Number ").replace("bank_d", "Bank ▼").replace("bank_u", "Bank ▲")}`;
    if (/^ctl\d$/.test(field)) return `CTL ${field[3]} à l'appel`;
    if (i !== undefined) return `${FIELD[field] || field} ${i + 1}`;
    return FIELD[field] || field;
  }

  /** Une modification du résumé → lignes { key, field, index, what, from, to }. */
  function lines(change, fields) {
    const { field, old, new: now } = change;
    if (change.chain) return [{ field, index: null, what: "Ordre de la chaîne", from: old, to: now }];
    if (Array.isArray(old)) {
      const out = [];
      old.forEach((v, i) => {
        if (v === now[i]) return;
        if (field === "assign_sw") {
          out.push({ field, index: i, what: `Assign ${i + 1}`, from: v ? "actif" : "inactif", to: now[i] ? "actif" : "inactif" });
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
    const labels = N.system_values[field];
    return labels ? labels[v] ?? v : Array.isArray(v) ? `${v.length} valeurs` : v;
  }

  return { value, label, lines, systemValue, loopName, slotName };
}
