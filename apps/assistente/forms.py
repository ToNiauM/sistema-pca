from django import forms


class PerguntaForm(forms.Form):
    pergunta = forms.CharField(
        label="Sua pergunta",
        max_length=1000,
        strip=True,
        widget=forms.Textarea(attrs={"rows": 2, "maxlength": 1000}),
    )
    requisicao_id = forms.CharField(max_length=64, widget=forms.HiddenInput)
    exercicio = forms.IntegerField(min_value=2000, max_value=2100, widget=forms.HiddenInput)

    def clean_pergunta(self):
        pergunta = (self.cleaned_data.get("pergunta") or "").strip()
        if not pergunta:
            raise forms.ValidationError("Digite uma pergunta.")
        return pergunta


class NovaConversaForm(forms.Form):
    exercicio = forms.IntegerField(min_value=2000, max_value=2100, required=False, widget=forms.HiddenInput)
