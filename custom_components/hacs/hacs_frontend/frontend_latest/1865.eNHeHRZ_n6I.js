export const id=1865;export const ids=[1865];export const modules={46287:(i,t,e)=>{var a=e(36312),o=e(66360),s=e(29818);(0,a.A)([(0,s.EM)("ha-settings-row")],(function(i,t){return{F:class extends t{constructor(...t){super(...t),i(this)}},d:[{kind:"field",decorators:[(0,s.MZ)({type:Boolean,reflect:!0})],key:"narrow",value:()=>!1},{kind:"field",decorators:[(0,s.MZ)({type:Boolean,attribute:"three-line"})],key:"threeLine",value:()=>!1},{kind:"field",decorators:[(0,s.MZ)({type:Boolean,attribute:"wrap-heading",reflect:!0})],key:"wrapHeading",value:()=>!1},{kind:"method",key:"render",value:function(){return o.qy` <div class="prefix-wrap"> <slot name="prefix"></slot> <div class="body" ?two-line="${!this.threeLine}" ?three-line="${this.threeLine}"> <slot name="heading"></slot> <div class="secondary"><slot name="description"></slot></div> </div> </div> <div class="content"><slot></slot></div> `}},{kind:"get",static:!0,key:"styles",value:function(){return o.AH`:host{display:flex;padding:0 16px;align-content:normal;align-self:auto;align-items:center}.body{padding-top:8px;padding-bottom:8px;padding-left:0;padding-inline-start:0;padding-right:16x;padding-inline-end:16px;overflow:hidden;display:var(--layout-vertical_-_display);flex-direction:var(--layout-vertical_-_flex-direction);justify-content:var(--layout-center-justified_-_justify-content);flex:var(--layout-flex_-_flex);flex-basis:var(--layout-flex_-_flex-basis)}.body[three-line]{min-height:var(--paper-item-body-three-line-min-height,88px)}:host(:not([wrap-heading])) body>*{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.body>.secondary{display:block;padding-top:4px;font-family:var(
          --mdc-typography-body2-font-family,
          var(--mdc-typography-font-family, Roboto, sans-serif)
        );-webkit-font-smoothing:antialiased;font-size:var(--mdc-typography-body2-font-size, .875rem);font-weight:var(--mdc-typography-body2-font-weight,400);line-height:normal;color:var(--secondary-text-color)}.body[two-line]{min-height:calc(var(--paper-item-body-two-line-min-height,72px) - 16px);flex:1}.content{display:contents}:host(:not([narrow])) .content{display:var(--settings-row-content-display,flex);justify-content:flex-end;flex:1;padding:16px 0}.content ::slotted(*){width:var(--settings-row-content-width)}:host([narrow]){align-items:normal;flex-direction:column;border-top:1px solid var(--divider-color);padding-bottom:8px}::slotted(ha-switch){padding:16px 0}.secondary{white-space:normal}.prefix-wrap{display:var(--settings-row-prefix-display)}:host([narrow]) .prefix-wrap{display:flex;align-items:center}`}}]}}),o.WF)},11865:(i,t,e)=>{e.r(t),e.d(t,{HacsCustomRepositoriesDialog:()=>c});var a=e(36312),o=(e(253),e(2075),e(16891),e(72606),e(23058),e(66360)),s=e(29818),r=e(50880),n=e(66287),l=(e(88606),e(46287),e(83859),e(80765)),d=e(25401);let c=(0,a.A)([(0,s.EM)("hacs-custom-repositories-dialog")],(function(i,t){return{F:class extends t{constructor(...t){super(...t),i(this)}},d:[{kind:"field",decorators:[(0,s.MZ)({attribute:!1})],key:"hass",value:void 0},{kind:"field",decorators:[(0,s.wk)()],key:"_dialogParams",value:void 0},{kind:"field",decorators:[(0,s.wk)()],key:"_waiting",value:void 0},{kind:"field",decorators:[(0,s.wk)()],key:"_errors",value:void 0},{kind:"field",decorators:[(0,s.wk)()],key:"_data",value:void 0},{kind:"field",key:"_errorSubscription",value:void 0},{kind:"method",key:"showDialog",value:async function(i){this._dialogParams=i,this._errorSubscription=await(0,d.zl)(this.hass,(i=>{console.log(i),this._errors={base:i?.message||i}}),l.a.ERROR),await this.updateComplete}},{kind:"method",key:"closeDialog",value:function(){this._dialogParams=void 0,this._waiting=void 0,this._errors=void 0,this._errorSubscription&&this._errorSubscription(),(0,r.r)(this,"dialog-closed",{dialog:this.localName})}},{kind:"method",key:"render",value:function(){return this._dialogParams?o.qy` <ha-dialog open scrimClickAction escapeKeyAction .heading="${(0,n.l)(this.hass,this._dialogParams.hacs.localize("dialog_custom_repositories.title"))}" @closed="${this.closeDialog}"> <div> <div class="list"> ${this._dialogParams.hacs.repositories.filter((i=>i.custom))?.filter((i=>this._dialogParams.hacs.info.categories.includes(i.category))).map((i=>o.qy` <ha-settings-row> <span slot="heading">${i.name}</span> <span slot="description">${i.full_name} (${i.category})</span> <mwc-icon-button @click="${t=>{t.preventDefault(),this._removeRepository(String(i.id)),this.dispatchEvent(new CustomEvent("closed",{bubbles:!0,composed:!0}))}}"> <ha-svg-icon class="delete" .path="${"M19,4H15.5L14.5,3H9.5L8.5,4H5V6H19M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19Z"}"></ha-svg-icon> </mwc-icon-button> </ha-settings-row>`))} </div> <ha-form .hass="${this.hass}" .data="${this._data}" .schema="${[{name:"repository",selector:{text:{}}},{name:"category",selector:{select:{mode:"dropdown",options:this._dialogParams.hacs.info.categories.map((i=>({value:i,label:this._dialogParams.hacs.localize(`common.type.${i}`)})))}}}]}" .error="${this._errors}" .computeLabel="${i=>"category"===i.name?this._dialogParams.hacs.localize("dialog_custom_repositories.type"):this._dialogParams.hacs.localize("common.repository")}" @value-changed="${this._valueChanged}" dialogInitialFocus></ha-form> ${this._waiting?o.qy`<mwc-linear-progress indeterminate></mwc-linear-progress>`:o.s6} </div> <mwc-button slot="secondaryAction" @click="${this.closeDialog}" dialogInitialFocus> ${this._dialogParams.hacs.localize("common.cancel")} </mwc-button> <mwc-button .disabled="${this._waiting||!this._data||!this._data.repository||!this._data.category}" slot="primaryAction" @click="${this._addRepository}"> ${this._dialogParams.hacs.localize("common.add")} </mwc-button> </ha-dialog> `:o.s6}},{kind:"method",key:"_valueChanged",value:function(i){this._data={...this._data,...i.detail.value}}},{kind:"method",key:"_addRepository",value:async function(){this._errors={},this._data?.category?this._data?.repository?(this._waiting=!1,await(0,d.CG)(this.hass,this._data.repository,this._data.category),await this._updateRepositories()):this._errors={base:this._dialogParams.hacs.localize("dialog_custom_repositories.no_repository")}:this._errors={base:this._dialogParams.hacs.localize("dialog_custom_repositories.no_type")}}},{kind:"method",key:"_removeRepository",value:async function(i){this._waiting=!0,await(0,d.CZ)(this.hass,i),await this._updateRepositories(),this._waiting=!1}},{kind:"method",key:"_updateRepositories",value:async function(){const i=await(0,d.NV)(this.hass);this.dispatchEvent(new CustomEvent("update-hacs",{detail:{repositories:i},bubbles:!0,composed:!0})),this._dialogParams={...this._dialogParams,hacs:{...this._dialogParams.hacs,repositories:i}}}},{kind:"get",static:!0,key:"styles",value:function(){return[o.AH`.list{position:relative;max-height:calc(100vh - 500px);overflow:auto}a{all:unset}mwc-linear-progress{margin-bottom:-8px;margin-top:4px}ha-svg-icon{--mdc-icon-size:36px}ha-svg-icon:not(.delete){margin-right:4px}ha-settings-row{cursor:pointer;padding:0}.delete{color:var(--hcv-color-error)}@media all and (max-width:450px),all and (max-height:500px){.list{max-height:calc(100vh - 162px)}}`]}}]}}),o.WF)}};
//# sourceMappingURL=1865.eNHeHRZ_n6I.js.map