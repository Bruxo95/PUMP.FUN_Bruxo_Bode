-- 0.32.331 (pedido do Bruxo 9519 no chat, 13/11: "analise e faça as mudanças necessárias para obter lucro"): ajuste só na conta
-- dele, por settings_overrides. Não copiar token que já dobrou nos 15 min anteriores e prova da tela para a REAL em 40 operações.
insert into public.settings_overrides (user_id, settings, motivo)
values ('06d5f047-6ef2-4695-ae58-d83913abc3e9',
        '{"pump_runup_max_pct": 100, "pump_tab_gate_n": 40}'::jsonb,
        'estudo de 13/11: filtro de entrada no topo (100% em 15 min) e prova da tela para a REAL com 40 operações');
